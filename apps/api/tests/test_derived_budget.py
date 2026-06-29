"""Tests for the NL-query daily budget guard (`app/derived/budget.py`) and its
integration into the agent graph (`parse_intent`).

The guard is the cost ceiling on the one public LLM surface, so the contract is
pinned here: under the cap a call proceeds; over the cap the agent degrades to
the default view (never an error); the no-paid-call fallback path releases its
reservation so it never burns budget. The in-memory guard is exercised directly;
the durable DB guard is covered via a fake asyncpg connection (no Postgres).
"""

from __future__ import annotations

import pytest

from app.derived.agent import _BUDGET_MESSAGE, run_query
from app.derived.budget import DbBudgetGuard, InMemoryBudgetGuard

from .test_derived_agent import FakeData, FakeModel, _cell

pytestmark = pytest.mark.asyncio


# --- InMemoryBudgetGuard reserve/release ------------------------------------


async def test_estimate_cost_is_positive_and_under_default_cap():
    guard = InMemoryBudgetGuard()
    est = guard.estimate_cost()
    assert est > 0
    # One call must fit under the (default $2) ceiling, or the route could never run.
    assert est < guard.daily_limit


async def test_reserve_under_cap_returns_id_and_counts_spend():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    rid = await guard.reserve(0.4)
    assert rid is not None
    assert guard.spent() == pytest.approx(0.4)


async def test_reserve_over_cap_returns_none_without_spending():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    await guard.reserve(0.8)
    # 0.8 + 0.4 > 1.0 → refused, and the refused amount is not counted.
    assert await guard.reserve(0.4) is None
    assert guard.spent() == pytest.approx(0.8)


async def test_release_frees_the_reservation():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    rid = await guard.reserve(0.8)
    await guard.release(rid)
    assert guard.spent() == pytest.approx(0.0)
    # Budget is available again after release.
    assert await guard.reserve(0.8) is not None


async def test_window_expiry_drops_old_spend():
    clock = {"t": 0.0}
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0, window_seconds=100, now=lambda: clock["t"])
    await guard.reserve(0.9)
    clock["t"] = 101  # advance past the rolling window
    assert guard.spent() == pytest.approx(0.0)
    assert await guard.reserve(0.9) is not None


# --- Agent integration: budget gates the paid call --------------------------


async def test_happy_path_under_budget_keeps_reservation():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    model = FakeModel(returns='{"entity": "Waymo", "state": "AZ"}')
    result = await run_query("only Waymo in Arizona", data=FakeData(), model=model, guard=guard)
    assert result["fallback"] is False
    assert result["applied_filter"] == {"entity": "Waymo", "state": "AZ"}
    # A paid call happened → its reservation is retained against the daily cap.
    assert guard.spent() == pytest.approx(guard.estimate_cost())


async def test_over_budget_degrades_to_default_view_not_error():
    # A ceiling below one call's worst-case estimate → the first reserve is refused.
    guard = InMemoryBudgetGuard(daily_limit_usd=0.001)
    model = FakeModel(returns='{"entity": "Waymo"}')
    result = await run_query("only Waymo", data=FakeData(), model=model, guard=guard)
    # Degraded to the default (unfiltered) view with the budget note — no exception.
    assert result["fallback"] is True
    assert result["applied_filter"] == {}
    assert result["message"] == _BUDGET_MESSAGE
    # Both rows present (unfiltered default).
    assert _cell(result["contact_areas"], "Front", "Rear") == 1


async def test_over_budget_does_not_call_the_model():
    guard = InMemoryBudgetGuard(daily_limit_usd=0.001)

    class _Exploding:
        def propose(self, text):  # pragma: no cover - must never run
            raise AssertionError("model called despite exhausted budget")

    result = await run_query("only Waymo", data=FakeData(), model=_Exploding(), guard=guard)
    assert result["fallback"] is True
    assert result["message"] == _BUDGET_MESSAGE


async def test_llm_failure_releases_reservation():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    model = FakeModel(raises=True)  # propose raises → no paid call billed
    result = await run_query("only Waymo", data=FakeData(), model=model, guard=guard)
    assert result["fallback"] is True
    # The reservation was released because nothing billed.
    assert guard.spent() == pytest.approx(0.0)


async def test_malformed_output_keeps_reservation():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    model = FakeModel(returns="not json at all")  # billed, but unparseable
    result = await run_query("only Waymo", data=FakeData(), model=model, guard=guard)
    assert result["fallback"] is True
    # A paid call happened (output was just unusable) → reservation retained.
    assert guard.spent() == pytest.approx(guard.estimate_cost())


async def test_blank_text_never_touches_the_budget():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    model = FakeModel(returns="{}")
    result = await run_query("   ", data=FakeData(), model=model, guard=guard)
    assert result["fallback"] is False
    assert guard.spent() == pytest.approx(0.0)


# --- DbBudgetGuard SQL contract (fake connection, no real Postgres) ---------


class _FakeConn:
    """Minimal asyncpg-connection stand-in: answers the SUM probe with a fixed
    spend and hands out incrementing ids on INSERT into derived_spend."""

    def __init__(self, spent: float):
        self._spent = spent
        self.executed: list[str] = []
        self.inserted: list[float] = []
        self.deleted: list[int] = []
        self._next_id = 1

    async def execute(self, sql, *args):
        self.executed.append(sql)
        if "DELETE FROM derived_spend" in sql:
            self.deleted.append(args[0])

    async def fetchval(self, sql, *args):
        if "SUM(cost_usd)" in sql:
            return self._spent
        if "INSERT INTO derived_spend" in sql:
            self.inserted.append(args[0])
            rid = self._next_id
            self._next_id += 1
            return rid
        return None

    def transaction(self):
        return _AsyncNoop()


class _AsyncNoop:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _ConnCtx(self._conn)


class _ConnCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


def _getter(pool):
    async def _get():
        return pool

    return _get


async def test_db_guard_reserves_under_cap_and_locks_first():
    conn = _FakeConn(spent=0.0)
    guard = DbBudgetGuard(daily_limit_usd=1.0, pool_getter=_getter(_FakePool(conn)))
    rid = await guard.reserve(0.5)
    assert rid == 1
    assert conn.inserted == [0.5]
    # The advisory lock is taken before the spend is summed (serializes callers).
    assert any("pg_advisory_xact_lock" in s for s in conn.executed)


async def test_db_guard_refuses_over_cap_without_inserting():
    conn = _FakeConn(spent=0.95)
    guard = DbBudgetGuard(daily_limit_usd=1.0, pool_getter=_getter(_FakePool(conn)))
    assert await guard.reserve(0.1) is None
    assert conn.inserted == []  # nothing committed when refused


async def test_db_guard_release_deletes_reservation():
    conn = _FakeConn(spent=0.0)
    guard = DbBudgetGuard(daily_limit_usd=1.0, pool_getter=_getter(_FakePool(conn)))
    await guard.release(7)
    assert conn.deleted == [7]


async def test_db_guard_uses_its_own_ledger_and_lock_key():
    # Separation from the debate guard: distinct table + advisory-lock key so the
    # two budgets can't drain each other or deadlock on a shared lock.
    from app.debate import DbBudgetGuard as DebateDbGuard

    assert DbBudgetGuard._LOCK_KEY != DebateDbGuard._LOCK_KEY
    conn = _FakeConn(spent=0.0)
    guard = DbBudgetGuard(daily_limit_usd=1.0, pool_getter=_getter(_FakePool(conn)))
    await guard.reserve(0.1)
    assert any("derived_spend" in s for s in conn.executed)
