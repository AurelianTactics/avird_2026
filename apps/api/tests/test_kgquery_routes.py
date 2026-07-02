"""Tests for the KG-query routes (P3 web delivery, U17).

Route tests override the graph seam, model, and budget guard with in-memory
fakes (no key, no Neo4j), mirroring test_nlsql_routes.py. The contract: the
status route degrades gracefully (card still present when the graph is down),
and the ask route never 500s.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.kgquery.budget import InMemoryBudgetGuard, get_kgquery_budget_guard
from app.kgquery.routes import get_cypher_model, get_kg_data
from app.main import app
from tests.test_kgquery_agent import VALID_CYPHER, FakeCypherModel, FakeKgData


class CountingKgData(FakeKgData):
    """Status route needs count queries; answer them from canned totals."""

    async def execute(self, cypher):
        if "count(n)" in cypher:
            return [{"n": 431}]
        if "count(r)" in cypher:
            return [{"n": 987}]
        return await super().execute(cypher)


def _override(data, model, guard=None):
    app.dependency_overrides[get_kg_data] = lambda: data
    app.dependency_overrides[get_cypher_model] = lambda: model
    app.dependency_overrides[get_kgquery_budget_guard] = lambda: guard or InMemoryBudgetGuard()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


# --- GET /kgquery/status ------------------------------------------------------


def test_status_returns_counts_and_card():
    _override(CountingKgData(), FakeCypherModel())
    r = client.get("/kgquery/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["nodes"] == 431
    assert body["relationships"] == 987
    assert "Incident" in body["card"]["labels"]
    assert "OPERATED_BY" in body["card"]["relationship_types"]
    assert ["Incident", "INVOLVES", "Vehicle"] in body["card"]["patterns"]


def test_status_degrades_with_card_when_graph_down():
    _override(CountingKgData(unreachable=True), FakeCypherModel())
    r = client.get("/kgquery/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    # The card comes from the committed yaml — still there for the sidebar.
    assert "Incident" in body["card"]["labels"]


# --- POST /kgquery/ask --------------------------------------------------------


def test_ask_happy_path_returns_cypher_and_rows():
    _override(FakeKgData(), FakeCypherModel(responses=[VALID_CYPHER]))
    r = client.post("/kgquery/ask", json={"question": "companies by incidents"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is False
    assert body["graph_available"] is True
    assert body["row_count"] == 2
    assert "OPERATED_BY" in body["cypher"]


def test_ask_never_500s_on_bad_model():
    # Model only ever returns a write -> validator rejects every attempt -> fallback.
    _override(FakeKgData(), FakeCypherModel(responses=["MATCH (n) DETACH DELETE n"] * 5))
    r = client.post("/kgquery/ask", json={"question": "delete everything"})
    assert r.status_code == 200
    assert r.json()["fallback"] is True


def test_ask_graph_down_is_a_renderable_degrade():
    _override(FakeKgData(unreachable=True), FakeCypherModel())
    r = client.post("/kgquery/ask", json={"question": "anything"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert body["graph_available"] is False


def test_ask_over_length_is_rejected_before_any_paid_call():
    model = FakeCypherModel()
    _override(FakeKgData(), model)
    r = client.post("/kgquery/ask", json={"question": "x" * 501})
    assert r.status_code == 422
    assert model.calls == 0


def test_ask_budget_tripped_degrades_to_fallback():
    model = FakeCypherModel()
    _override(FakeKgData(), model, guard=InMemoryBudgetGuard(daily_limit_usd=0.0))
    r = client.post("/kgquery/ask", json={"question": "companies"})
    assert r.status_code == 200
    assert r.json()["fallback"] is True
    assert model.calls == 0
