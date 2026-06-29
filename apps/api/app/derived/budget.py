"""Daily USD budget guard for the NL-query agent (``POST /derived/query``).

The default heatmap render is deterministic and LLM-free (plan KTD 4), but the
NL-query path makes **one paid Claude call per request on a public surface**.
Per-call cost is tiny (Haiku, <=256 output tokens over a <=500-char prompt) yet
*aggregate* spend is otherwise unbounded — a script hammering the endpoint bills
one call each time. This guard caps rolling-24h spend so abuse can't run up the
bill; over the cap the route degrades to the default view (never an error),
mirroring the agent's "always renderable" contract (KTD 5).

It deliberately mirrors the debate budget guard (`app/debate.py`) but stays a
**separate** module with its own ceiling (``DERIVED_DAILY_BUDGET_USD``) and ledger
(``derived_spend``), so the two LLM features can't drain each other's budget and
a change to one can't regress the other.

Semantics — **reserve-then-check**, no reconcile: a call reserves its worst-case
estimated cost *before* the paid call runs (so concurrent requests see each other
and can't all slip past the cap at once), and that reservation is kept as-is. The
estimate is the worst case for this path, so keeping it (rather than reconciling
down to the real token count) only ever *over*-counts — the guard fails safe
toward spending less. ``release()`` drops the reservation when no paid call
actually happened (LLM unavailable / no key), so the no-call fallback path never
burns budget.

Storage is durable Postgres so the cap survives api restarts and holds across
replicas — an in-memory cap would reset on every redeploy. The guard is injected
via a FastAPI dependency the tests override with the in-memory variant (no DB).
"""

from __future__ import annotations

import os
import threading
import time

# claude-haiku-4-5 pricing: $1.00 / MTok input, $5.00 / MTok output. Mirrors the
# debate guard; the NL agent pins the same model family (see agent.DEFAULT_MODEL).
HAIKU_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
HAIKU_OUTPUT_USD_PER_TOKEN = 5.00 / 1_000_000
WINDOW_SECONDS = 24 * 60 * 60
_CHARS_PER_TOKEN = 4

# Worst-case input for one call: the 500-char query cap (mirrors QueryRequest /
# the web proxy's MAX_TEXT) plus the system-prompt scaffold (~1500 chars), at
# ~4 chars per token. Output is bounded by the agent's max_tokens (256).
_ESTIMATE_INPUT_CHARS = 500 + 1500
_ESTIMATE_OUTPUT_TOKENS = 256


def _default_budget_usd() -> float:
    try:
        return float(os.environ.get("DERIVED_DAILY_BUDGET_USD", "2"))
    except (TypeError, ValueError):
        return 2.0


class BudgetGuard:
    """Rolling-window USD spend cap with reserve-then-check semantics.

    Subclasses provide storage: :class:`InMemoryBudgetGuard` (process-local, the
    test seam) and :class:`DbBudgetGuard` (durable, the production default).
    """

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
        """Worst-case USD for one NL-query call — reserved up front, before the
        real token count is known. Uses this guard's prices so it tracks them."""
        est_input_tokens = _ESTIMATE_INPUT_CHARS / _CHARS_PER_TOKEN
        return est_input_tokens * self.input_price + _ESTIMATE_OUTPUT_TOKENS * self.output_price

    async def reserve(self, estimated_cost: float) -> int | None:  # pragma: no cover
        raise NotImplementedError

    async def release(self, reservation: int) -> None:  # pragma: no cover
        raise NotImplementedError


class InMemoryBudgetGuard(BudgetGuard):
    """Process-local guard. Correct for a single instance but does **not** survive
    restarts or coordinate across instances — that's :class:`DbBudgetGuard`. Kept
    as the test seam (no DB needed)."""

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
    """Durable guard backed by a ``derived_spend`` ledger in Postgres. Survives api
    restarts and is correct across instances. The reserve check + insert run under
    a transaction-scoped advisory lock so concurrent callers serialize on the spend
    total — no overshoot. The table is created lazily (``IF NOT EXISTS``) on first
    use; it's operational state owned by the api, not part of the crash-data
    pipeline."""

    # Arbitrary 64-bit key, distinct from the debate guard's so the two ledgers
    # never contend on the same advisory lock. "AVDRVD".
    _LOCK_KEY = 0x4156_4452_5644

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
            "CREATE TABLE IF NOT EXISTS derived_spend ("
            "  id BIGSERIAL PRIMARY KEY,"
            "  ts timestamptz NOT NULL DEFAULT now(),"
            "  cost_usd double precision NOT NULL)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS derived_spend_ts_idx ON derived_spend (ts)")
        self._table_ready = True

    async def reserve(self, estimated_cost: float) -> int | None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await self._ensure_table(conn)
            async with conn.transaction():
                # Serialize concurrent reservations; lock auto-releases at commit.
                await conn.execute("SELECT pg_advisory_xact_lock($1)", self._LOCK_KEY)
                spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM derived_spend "
                    "WHERE ts > now() - make_interval(secs => $1)",
                    float(self.window_seconds),
                )
                if float(spent) + estimated_cost > self.daily_limit:
                    return None
                return await conn.fetchval(
                    "INSERT INTO derived_spend (cost_usd) VALUES ($1) RETURNING id",
                    estimated_cost,
                )

    async def release(self, reservation: int) -> None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM derived_spend WHERE id = $1", reservation)


_budget_guard: BudgetGuard = DbBudgetGuard()


def get_budget_guard() -> BudgetGuard:
    """FastAPI dependency. Production uses the durable DB-backed guard; tests
    override with a low-cap :class:`InMemoryBudgetGuard`."""
    return _budget_guard


__all__ = [
    "BudgetGuard",
    "InMemoryBudgetGuard",
    "DbBudgetGuard",
    "get_budget_guard",
]
