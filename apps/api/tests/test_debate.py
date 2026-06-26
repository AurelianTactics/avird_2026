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
    BudgetGuard,
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
    if guard is not None:
        app.dependency_overrides[get_budget_guard] = lambda: guard


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


def test_budget_guard_returns_429_once_tripped():
    # Tiny cap; the first call's stub usage spends past it, so the second 429s.
    guard = BudgetGuard(daily_limit_usd=0.0001)
    client = StubClient(usage=Usage(input_tokens=1000, output_tokens=1000))
    _use(client=client, guard=guard)
    try:
        with TestClient(app) as http:
            first = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": [],
                    "user_argument": "round one",
                },
            )
            assert first.status_code == 200  # records spend
            second = http.post(
                "/incidents/RPT-9/debate/turn",
                json={
                    "user_position": "av_at_fault",
                    "transcript": [],
                    "user_argument": "round two",
                },
            )
            assert second.status_code == 429
            assert "break" in second.json()["detail"]
            # The blocked call never reached the LLM.
            assert client.advocate_calls == 1
    finally:
        _clear()


def test_budget_guard_blocks_judge_too():
    guard = BudgetGuard(daily_limit_usd=0.0001)
    client = StubClient(usage=Usage(input_tokens=1000, output_tokens=1000))
    _use(client=client, guard=guard)
    try:
        with TestClient(app) as http:
            http.post(
                "/incidents/RPT-9/debate/turn",
                json={"user_position": "av_at_fault", "transcript": [], "user_argument": "spend"},
            )
            resp = http.post(
                "/incidents/RPT-9/debate/judge",
                json={"transcript": [{"role": "user", "content": "x"}]},
            )
            assert resp.status_code == 429
    finally:
        _clear()


# --- budget guard unit ------------------------------------------------------


def test_budget_guard_window_rolls_off():
    clock = {"t": 1000.0}
    guard = BudgetGuard(daily_limit_usd=1.0, window_seconds=100, now=lambda: clock["t"])
    guard.input_price = guard.output_price = 1.0  # $1 per token for easy math
    guard.record(Usage(input_tokens=1, output_tokens=0))  # $1 spent at t=1000
    assert guard.spent() == 1.0
    assert guard.exceeded() is True
    clock["t"] = 1101.0  # >100s later — event rolls out of the window
    assert guard.spent() == 0.0
    assert guard.exceeded() is False
