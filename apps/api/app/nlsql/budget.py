"""Daily USD budget guard for the text-to-SQL route (``POST /nlsql/query``).

The plan's live-exposure rule (KTD-5, R7): any phase that goes on a web surface
inherits the budget-guard discipline. This mirrors ``derived/budget.py`` and
``debate.py`` — a durable rolling-24h ledger with reserve-then-check semantics —
but stays a **separate** module with its own ceiling (``NLSQL_DAILY_BUDGET_USD``),
ledger (``nlsql_spend``), and advisory lock, so the three paid LLM surfaces can't
drain each other's budget.

**Why its own estimate (the KTD-5 caveat):** the text-to-SQL prompt is much larger
than the NL-filter one — a generated schema card (every column), value samples,
few-shot exemplars, and the repair loop makes *multiple* calls per question. The
verbatim ``derived`` estimate (`500 + 1500` input chars, 256 output tokens) would
under-reserve and the daily cap wouldn't mean what the env var says. This guard
sizes the estimate to the actual P1 prompt/output budget. The agent reserves once
per author attempt, so a repair loop naturally counts each paid call.
"""

from __future__ import annotations

import os
import threading
import time

# claude-haiku-4-5 pricing: $1.00 / MTok input, $5.00 / MTok output (the P1
# structural call pins the same model family as the NL agent, agent.DEFAULT_MODEL).
HAIKU_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
HAIKU_OUTPUT_USD_PER_TOKEN = 5.00 / 1_000_000
WINDOW_SECONDS = 24 * 60 * 60
_CHARS_PER_TOKEN = 4

# Worst-case input for one author call: schema card (all columns) + value samples
# + few-shot + the question + a repair observation, ~6000 chars at ~4 chars/token.
# Output is bounded by the agent's max_tokens (512, see agent.ClaudeSqlModel).
_ESTIMATE_INPUT_CHARS = 6000
_ESTIMATE_OUTPUT_TOKENS = 512


def _default_budget_usd() -> float:
    try:
        return float(os.environ.get("NLSQL_DAILY_BUDGET_USD", "2"))
    except (TypeError, ValueError):
        return 2.0


class BudgetGuard:
    """Rolling-window USD spend cap with reserve-then-check semantics.

    Subclasses provide storage: :class:`InMemoryBudgetGuard` (the test seam) and
    :class:`DbBudgetGuard` (durable, the production default)."""

    def __init__(
        self,
        daily_limit_usd: float | None = None,
        *,
        window_seconds: int = WINDOW_SECONDS,
        input_price: float = HAIKU_INPUT_USD_PER_TOKEN,
        output_price: float = HAIKU_OUTPUT_USD_PER_TOKEN,
    ):
        self.daily_limit = _default_budget_usd() if daily_limit_usd is None else daily_limit_usd
        self.window_seconds = window_seconds
        self.input_price = input_price
        self.output_price = output_price

    def estimate_cost(self) -> float:
        """Worst-case USD for one author call, sized to the P1 prompt (KTD-5)."""
        est_input_tokens = _ESTIMATE_INPUT_CHARS / _CHARS_PER_TOKEN
        return est_input_tokens * self.input_price + _ESTIMATE_OUTPUT_TOKENS * self.output_price

    async def reserve(self, estimated_cost: float) -> int | None:  # pragma: no cover
        raise NotImplementedError

    async def release(self, reservation: int) -> None:  # pragma: no cover
        raise NotImplementedError


class InMemoryBudgetGuard(BudgetGuard):
    """Process-local guard. Correct for one instance, does not survive restarts —
    that's :class:`DbBudgetGuard`. The test seam (no DB needed)."""

    def __init__(self, *args, now=time.monotonic, **kwargs):
        super().__init__(*args, **kwargs)
        self._now = now
        self._events: dict[int, tuple[float, float]] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def _spent_locked(self, t: float) -> float:
        cutoff = t - self.window_seconds
        for rid in [k for k, (ts, _) in self._events.items() if ts < cutoff]:
            del self._events[rid]
        return sum(cost for _, cost in self._events.values())

    def spent(self) -> float:
        with self._lock:
            return self._spent_locked(self._now())

    async def reserve(self, estimated_cost: float) -> int | None:
        with self._lock:
            t = self._now()
            if self._spent_locked(t) + estimated_cost > self.daily_limit:
                return None
            self._seq += 1
            self._events[self._seq] = (t, estimated_cost)
            return self._seq

    async def release(self, reservation: int) -> None:
        with self._lock:
            self._events.pop(reservation, None)


class DbBudgetGuard(BudgetGuard):
    """Durable guard backed by an ``nlsql_spend`` ledger. Survives restarts and is
    correct across instances; reserve+insert run under a transaction-scoped
    advisory lock so concurrent callers serialize on the spend total. The table is
    created lazily on first use."""

    # Distinct 64-bit key from the derived/debate guards so the ledgers never
    # contend on the same advisory lock. "AVNLSQ".
    _LOCK_KEY = 0x4156_4E4C_5351

    def __init__(self, *args, pool_getter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if pool_getter is None:
            from ..db import get_pool

            pool_getter = get_pool
        self._pool_getter = pool_getter
        self._table_ready = False

    async def _ensure_table(self, conn) -> None:
        if self._table_ready:
            return
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS nlsql_spend ("
            "  id BIGSERIAL PRIMARY KEY,"
            "  ts timestamptz NOT NULL DEFAULT now(),"
            "  cost_usd double precision NOT NULL)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS nlsql_spend_ts_idx ON nlsql_spend (ts)")
        self._table_ready = True

    async def reserve(self, estimated_cost: float) -> int | None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await self._ensure_table(conn)
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", self._LOCK_KEY)
                spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM nlsql_spend "
                    "WHERE ts > now() - make_interval(secs => $1)",
                    float(self.window_seconds),
                )
                if float(spent) + estimated_cost > self.daily_limit:
                    return None
                return await conn.fetchval(
                    "INSERT INTO nlsql_spend (cost_usd) VALUES ($1) RETURNING id",
                    estimated_cost,
                )

    async def release(self, reservation: int) -> None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM nlsql_spend WHERE id = $1", reservation)


_budget_guard: BudgetGuard = DbBudgetGuard()


def get_nlsql_budget_guard() -> BudgetGuard:
    """FastAPI dependency. Production uses the durable DB-backed guard; tests
    override with a low-cap :class:`InMemoryBudgetGuard`."""
    return _budget_guard


__all__ = [
    "BudgetGuard",
    "DbBudgetGuard",
    "InMemoryBudgetGuard",
    "get_nlsql_budget_guard",
]
