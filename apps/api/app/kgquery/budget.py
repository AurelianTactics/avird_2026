"""Daily USD budget guard for the KG-query route (``POST /kgquery/ask``).

Mirrors ``nlsql/budget.py`` — a durable rolling-24h ledger with reserve-then-
check semantics — but stays a **separate** module with its own ceiling
(``KGQUERY_DAILY_BUDGET_USD``), ledger (``kgquery_spend``), and advisory lock,
so the paid LLM surfaces can't drain each other's budget.

**The per-phase estimate (the KTD-5 caveat, third time):** the P3 prompt is
dominated by the rendered graph card — 29 labels, 41 relationship types, and
120 patterns, ~12.6K chars as rendered. Rather than copying a constant that
drifts when the card changes, the estimate is **measured from the rendered
card** at first use, plus headroom for the question and a repair observation.
Output is bounded by the agent's ``max_tokens`` (512).
"""

from __future__ import annotations

import os
import threading
import time

# claude-haiku-4-5 pricing: $1.00 / MTok input, $5.00 / MTok output (the P3
# structural call pins the same model family, agent.DEFAULT_MODEL).
HAIKU_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
HAIKU_OUTPUT_USD_PER_TOKEN = 5.00 / 1_000_000
WINDOW_SECONDS = 24 * 60 * 60
_CHARS_PER_TOKEN = 4

# Headroom on top of the measured card: question (500 cap), prior attempt +
# observation on a repair iteration, and the prompt scaffolding.
_PROMPT_OVERHEAD_CHARS = 2500
# Used only if the card can't be rendered (schema yaml unreadable) — sized to
# the measured v001 card so the guard still over-, not under-reserves.
_FALLBACK_CARD_CHARS = 13000
_ESTIMATE_OUTPUT_TOKENS = 512

_estimate_input_chars: int | None = None


def _estimate_chars() -> int:
    """Measure the rendered card once; fall back to a conservative constant."""
    global _estimate_input_chars
    if _estimate_input_chars is None:
        try:
            from .graph_card import load_graph_card

            card_chars = len(load_graph_card().render())
        except Exception:  # noqa: BLE001 — never let sizing break the guard
            card_chars = _FALLBACK_CARD_CHARS
        _estimate_input_chars = card_chars + _PROMPT_OVERHEAD_CHARS
    return _estimate_input_chars


def _default_budget_usd() -> float:
    try:
        return float(os.environ.get("KGQUERY_DAILY_BUDGET_USD", "2"))
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
        """Worst-case USD for one author call, sized from the rendered card (KTD-5)."""
        est_input_tokens = _estimate_chars() / _CHARS_PER_TOKEN
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
    """Durable guard backed by a ``kgquery_spend`` ledger. Survives restarts and
    is correct across instances; reserve+insert run under a transaction-scoped
    advisory lock so concurrent callers serialize on the spend total. The table
    is created lazily on first use."""

    # Distinct 64-bit key from the derived/debate/nlsql/rag guards so the
    # ledgers never contend on the same advisory lock. "AVKGQY".
    _LOCK_KEY = 0x4156_4B47_5159

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
            "CREATE TABLE IF NOT EXISTS kgquery_spend ("
            "  id BIGSERIAL PRIMARY KEY,"
            "  ts timestamptz NOT NULL DEFAULT now(),"
            "  cost_usd double precision NOT NULL)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS kgquery_spend_ts_idx ON kgquery_spend (ts)")
        self._table_ready = True

    async def reserve(self, estimated_cost: float) -> int | None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await self._ensure_table(conn)
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock($1)", self._LOCK_KEY)
                spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM kgquery_spend "
                    "WHERE ts > now() - make_interval(secs => $1)",
                    float(self.window_seconds),
                )
                if float(spent) + estimated_cost > self.daily_limit:
                    return None
                return await conn.fetchval(
                    "INSERT INTO kgquery_spend (cost_usd) VALUES ($1) RETURNING id",
                    estimated_cost,
                )

    async def release(self, reservation: int) -> None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM kgquery_spend WHERE id = $1", reservation)


_budget_guard: BudgetGuard = DbBudgetGuard()


def get_kgquery_budget_guard() -> BudgetGuard:
    """FastAPI dependency. Production uses the durable DB-backed guard; tests
    override with a low-cap :class:`InMemoryBudgetGuard`."""
    return _budget_guard


__all__ = [
    "BudgetGuard",
    "DbBudgetGuard",
    "InMemoryBudgetGuard",
    "get_kgquery_budget_guard",
]
