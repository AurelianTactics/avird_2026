"""Daily USD budget guard for the narrative-RAG route (``POST /rag/ask``).

The plan's live-exposure rule (KTD-5, R7): any phase that goes on a web surface
inherits the budget-guard discipline. This mirrors ``nlsql/budget.py`` — a
durable rolling-24h ledger with reserve-then-check semantics — but stays a
**separate** module with its own ceiling (``RAG_DAILY_BUDGET_USD``), ledger
(``rag_spend``), and advisory lock, so the paid LLM surfaces can't drain each
other's budget.

**Why its own estimate (the KTD-5 caveat):** the RAG loop makes up to two paid
calls per question — the answer call (haiku over the assembled narrative context)
and the faithfulness judge (a *larger* model, sonnet, over the same context plus
the answer). One shared per-call estimate must cover the pricier of the two, so
it is sized to the judge: sonnet pricing over a worst-case context (k narratives
at the per-chunk cap) with the answer's ``max_tokens`` as the output bound. The
agent reserves once per paid call, so the answer+judge pair naturally counts as
two reservations.
"""

from __future__ import annotations

import os
import threading
import time

# claude-sonnet-4-6 pricing: $3.00 / MTok input, $15.00 / MTok output. The judge
# (JUDGE_MODEL) is the priciest call in the loop, so the shared per-call estimate
# uses its rates — the haiku answer call is then over-reserved, which errs safe.
SONNET_INPUT_USD_PER_TOKEN = 3.00 / 1_000_000
SONNET_OUTPUT_USD_PER_TOKEN = 15.00 / 1_000_000
WINDOW_SECONDS = 24 * 60 * 60
_CHARS_PER_TOKEN = 4

# Worst-case input for one call: the assembled context (defaults in rag/context.py:
# ~5 chunks x ~1200 chars, doubled once by the broaden-retrieve repair) + the
# question + the answer being judged, ~14000 chars at ~4 chars/token. Output is
# bounded by the answer model's max_tokens (700, see agent.ClaudeRagModel).
_ESTIMATE_INPUT_CHARS = 14_000
_ESTIMATE_OUTPUT_TOKENS = 700


def _default_budget_usd() -> float:
    try:
        return float(os.environ.get("RAG_DAILY_BUDGET_USD", "2"))
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
        input_price: float = SONNET_INPUT_USD_PER_TOKEN,
        output_price: float = SONNET_OUTPUT_USD_PER_TOKEN,
    ):
        self.daily_limit = _default_budget_usd() if daily_limit_usd is None else daily_limit_usd
        self.window_seconds = window_seconds
        self.input_price = input_price
        self.output_price = output_price

    def estimate_cost(self) -> float:
        """Worst-case USD for one paid call, sized to the judge (KTD-5)."""
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
    """Durable guard backed by a ``rag_spend`` ledger. Survives restarts and is
    correct across instances; reserve+insert run under a transaction-scoped
    advisory lock so concurrent callers serialize on the spend total. The table is
    created lazily on first use."""

    # Distinct 64-bit key from the derived/debate/nlsql guards so the ledgers
    # never contend on the same advisory lock. "AVRAG".
    _LOCK_KEY = 0x41_5652_4147

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
            "CREATE TABLE IF NOT EXISTS rag_spend ("
            "  id BIGSERIAL PRIMARY KEY,"
            "  ts timestamptz NOT NULL DEFAULT now(),"
            "  cost_usd double precision NOT NULL)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS rag_spend_ts_idx ON rag_spend (ts)")
        self._table_ready = True

    async def reserve(self, estimated_cost: float) -> int | None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await self._ensure_table(conn)
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", self._LOCK_KEY)
                spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM rag_spend "
                    "WHERE ts > now() - make_interval(secs => $1)",
                    float(self.window_seconds),
                )
                if float(spent) + estimated_cost > self.daily_limit:
                    return None
                return await conn.fetchval(
                    "INSERT INTO rag_spend (cost_usd) VALUES ($1) RETURNING id",
                    estimated_cost,
                )

    async def release(self, reservation: int) -> None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM rag_spend WHERE id = $1", reservation)


_budget_guard: BudgetGuard = DbBudgetGuard()


def get_rag_budget_guard() -> BudgetGuard:
    """FastAPI dependency. Production uses the durable DB-backed guard; tests
    override with a low-cap :class:`InMemoryBudgetGuard`."""
    return _budget_guard


__all__ = [
    "BudgetGuard",
    "DbBudgetGuard",
    "InMemoryBudgetGuard",
    "get_rag_budget_guard",
]
