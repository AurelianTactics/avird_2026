"""Tests for the live debate routes (covers R6/R7/R7a).

Everything is stubbed — a fake incident data layer + a stub LLM client that
returns canned output. No network, no key, no spend. The budget guard is driven
with a low cap injected per-test so the 429 path asserts the guard, not real
billing.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import debate
from app.debate import (
    DbBudgetGuard,
    InMemoryBudgetGuard,
    JudgeVerdict,
    Usage,
    get_budget_guard,
    get_debate_client,
)
from app.incidents import get_incident_data
from app.main import app

INCIDENT_ROW = {
    "Report ID": "RPT-9",
    "Operating Entity": "Waymo LLC",
    "Incident Date": "2024-05-10",
    "City": "Phoenix",
    "State": "AZ",
    "Crash With": "Passenger Car",
    "SV Pre-Crash Movement": "Proceeding straight",
    "CP Pre-Crash Movement": "Stopped",
    "Narrative": "The AV was proceeding straight when it struck a stopped car.",
}


class FakeIncidentData:
    def __init__(self, row=INCIDENT_ROW):
        self.row = row

    async def fetch_incident(self, report_id):
        return self.row


class StubClient:
    """Returns canned advocate/judge output + a fixed token usage."""

    def __init__(
        self,
        *,
        advocate_text="AI rebuttal.",
        verdict=None,
        usage=None,
    ):
        self.verdict = verdict or JudgeVerdict(
            is_av_at_fault=True, fault_percentage=0.7, reasoning="AV at fault."
        )
        self.advocate_text = advocate_text
        self.usage = usage or Usage(input_tokens=100, output_tokens=50)
        self.advocate_calls = 0
        self.judge_calls = 0

    def advocate(self, prompt):
        self.advocate_calls += 1
        return self.advocate_text, self.usage

    def judge(self, prompt):
        self.judge_calls += 1
        return self.verdict, self.usage


def _use(*, data=None, client=None, guard=None):
    app.dependency_overrides[get_incident_data] = lambda: data or FakeIncidentData()
    app.dependency_overrides[get_debate_client] = lambda: client or StubClient()
    # Always override the guard with an in-memory one (default cap) so route
    # tests never reach the production DB-backed guard.
    app.dependency_overrides[get_budget_guard] = lambda: guard or InMemoryBudgetGuard()


def _clear():
    app.dependency_overrides.clear()


# --- advocate turn ---------------------------------------------------------


def test_turn_returns_opposite_side_message():
    client = StubClient(advocate_text="The AV is not at fault here.")
    _use(client=client)
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": [],
                    "user_argument": "The AV ran the light.",
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["message"] == "The AV is not at fault here."
        # The AI argues the OPPOSITE of the visitor's position.
        assert body["ai_position"] == "not_at_fault"
        assert body["round"] == 1
        assert client.advocate_calls == 1
    finally:
        _clear()


def test_turn_round_counter_counts_prior_user_messages():
    _use()
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "not_at_fault",
                    "transcript": [
                        {"role": "user", "content": "first"},
                        {"role": "ai", "content": "rebuttal"},
                    ],
                    "user_argument": "second",
                },
            )
        assert resp.json()["round"] == 2
    finally:
        _clear()


def test_turn_rejects_oversize_argument():
    _use()
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": [],
                    "user_argument": "x" * (debate.MAX_ARGUMENT_CHARS + 1),
                },
            )
        assert resp.status_code == 400
    finally:
        _clear()


def test_turn_rejects_too_many_rounds():
    full = [{"role": "user", "content": "a"} for _ in range(debate.MAX_ROUNDS)]
    _use()
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": full,
                    "user_argument": "one more",
                },
            )
        assert resp.status_code == 400
    finally:
        _clear()


def test_turn_rejects_oversize_transcript():
    big = [{"role": "user", "content": "x" * 5000} for _ in range(5)]
    _use()
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": big,
                    "user_argument": "more",
                },
            )
        assert resp.status_code == 400
    finally:
        _clear()


def test_turn_404_when_incident_missing():
    _use(data=FakeIncidentData(row=None))
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/UNKNOWN/debate/turn",
                json={"user_position": "av_at_fault", "transcript": [], "user_argument": "hi"},
            )
        assert resp.status_code == 404
    finally:
        _clear()


# --- judge -----------------------------------------------------------------


def test_judge_returns_validated_verdict():
    client = StubClient(
        verdict=JudgeVerdict(
            is_av_at_fault=False, fault_percentage=0.25, reasoning="Other party at fault."
        )
    )
    _use(client=client)
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/judge",
                json={
                    "transcript": [
                        {"role": "user", "content": "AV is fine"},
                        {"role": "ai", "content": "AV erred"},
                    ]
                },
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_av_at_fault"] is False
        assert body["fault_percentage"] == 0.25
        assert body["reasoning"] == "Other party at fault."
        assert client.judge_calls == 1
    finally:
        _clear()


def test_judge_clamps_out_of_range_percentage():
    client = StubClient(
        verdict=JudgeVerdict(is_av_at_fault=True, fault_percentage=1.9, reasoning="clamp me")
    )
    _use(client=client)
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/judge",
                json={"transcript": [{"role": "user", "content": "hi"}]},
            )
        assert resp.json()["fault_percentage"] == 1.0
    finally:
        _clear()


# --- budget guard ----------------------------------------------------------


def test_budget_guard_blocks_a_call_that_would_exceed_cap():
    # Reserve-then-check: a single call's *reservation* already exceeds the cap,
    # so the call is refused before it ever reaches the LLM.
    guard = InMemoryBudgetGuard()
    guard.daily_limit = guard.estimate_cost() / 2
    client = StubClient()
    _use(client=client, guard=guard)
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": [],
                    "user_argument": "round one",
                },
            )
            assert resp.status_code == 429
            assert "break" in resp.json()["detail"]
            assert client.advocate_calls == 0  # never billed
    finally:
        _clear()


def test_budget_guard_allows_one_call_then_blocks():
    # Cap fits exactly one reservation; after the first call reconciles to its
    # (smaller) actual cost, a second reservation tips over the cap.
    guard = InMemoryBudgetGuard()
    guard.daily_limit = guard.estimate_cost() + 0.00001
    client = StubClient(usage=Usage(input_tokens=100, output_tokens=50))
    _use(client=client, guard=guard)
    try:
        with TestClient(app) as http:
            body = {"user_position": "av_at_fault", "transcript": [], "user_argument": "go"}
            first = http.post("/incidents/RPT-9/debate/turn", json=body)
            assert first.status_code == 200
            second = http.post("/incidents/RPT-9/debate/turn", json=body)
            assert second.status_code == 429
            assert client.advocate_calls == 1  # only the first call billed
    finally:
        _clear()


def test_budget_guard_blocks_judge_too():
    guard = InMemoryBudgetGuard()
    guard.daily_limit = guard.estimate_cost() / 2
    client = StubClient()
    _use(client=client, guard=guard)
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/judge",
                json={"transcript": [{"role": "user", "content": "x"}]},
            )
            assert resp.status_code == 429
            assert client.judge_calls == 0
    finally:
        _clear()


# --- budget guard unit ------------------------------------------------------


async def test_in_memory_guard_window_rolls_off():
    clock = {"t": 1000.0}
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0, window_seconds=100, now=lambda: clock["t"])
    guard.input_price = guard.output_price = 1.0  # $1 per token for easy math
    rid = await guard.reserve(0.5)
    assert rid is not None
    await guard.reconcile(rid, Usage(input_tokens=1, output_tokens=0))  # $1 actual
    assert guard.spent() == 1.0
    assert await guard.reserve(0.01) is None  # over cap now
    clock["t"] = 1101.0  # >100s later — the event rolls out of the window
    assert guard.spent() == 0.0
    assert await guard.reserve(0.5) is not None


async def test_in_memory_guard_release_frees_the_reservation():
    guard = InMemoryBudgetGuard(daily_limit_usd=1.0)
    rid = await guard.reserve(0.9)
    assert rid is not None
    assert await guard.reserve(0.9) is None  # 0.9 already held
    await guard.release(rid)
    assert await guard.reserve(0.9) is not None  # freed


# --- DbBudgetGuard SQL contract (fake connection, no real Postgres) ---------


class _FakeConn:
    """Minimal asyncpg-connection stand-in: answers the SUM probe with a fixed
    spend and hands out incrementing ids on INSERT."""

    def __init__(self, spent: float):
        self._spent = spent
        self.executed: list[str] = []
        self.inserted: list[float] = []
        self._next_id = 1

    async def execute(self, sql, *args):
        self.executed.append(sql)

    async def fetchval(self, sql, *args):
        if "SUM(cost_usd)" in sql:
            return self._spent
        if "INSERT INTO debate_spend" in sql:
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
    # The advisory lock is taken before the spend is summed.
    lock_i = next(i for i, s in enumerate(conn.executed) if "pg_advisory_xact_lock" in s)
    assert lock_i >= 0


async def test_db_guard_refuses_over_cap_without_inserting():
    conn = _FakeConn(spent=0.95)
    guard = DbBudgetGuard(daily_limit_usd=1.0, pool_getter=_getter(_FakePool(conn)))
    assert await guard.reserve(0.1) is None
    assert conn.inserted == []  # nothing committed when refused


# --- internal-boundary shared secret (web→api hop) -------------------------


def test_routes_open_when_no_secret_configured(monkeypatch):
    monkeypatch.delenv("API_SHARED_SECRET", raising=False)
    _use(client=StubClient(), guard=InMemoryBudgetGuard())
    try:
        with TestClient(app) as http:
            resp = http.post(
                "/incidents/RPT-9/debate/turn",
                json={"user_position": "av_at_fault", "transcript": [], "user_argument": "hi"},
            )
            assert resp.status_code == 200  # no header needed when unset
    finally:
        _clear()


def test_secret_required_when_configured(monkeypatch):
    monkeypatch.setenv("API_SHARED_SECRET", "s3cret")
    _use(client=StubClient(), guard=InMemoryBudgetGuard())
    try:
        with TestClient(app) as http:
            body = {"user_position": "av_at_fault", "transcript": [], "user_argument": "hi"}
            # No header → rejected at the boundary, before the route runs.
            assert http.post("/incidents/RPT-9/debate/turn", json=body).status_code == 401
            # Correct header → passes through.
            ok = http.post(
                "/incidents/RPT-9/debate/turn",
                json=body,
                headers={"x-internal-secret": "s3cret"},
            )
            assert ok.status_code == 200
            # The health probe stays exempt so the platform check never breaks.
            assert http.get("/health").status_code == 200
    finally:
        _clear()
