"""Tests for the text-to-SQL routes (P1 web delivery).

Route tests override the data seam, model, and budget guard with in-memory fakes
(no key, no Postgres), mirroring test_derived_routes.py. The contract: the schema
route degrades gracefully, and the query route never 500s on a bad query.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.nlsql import schema_card as sc
from app.nlsql import validate as v
from app.nlsql.budget import InMemoryBudgetGuard, get_nlsql_budget_guard
from app.nlsql.routes import get_nlsql_data, get_sql_model

CARD = sc.SchemaCard(
    table="treated_incident_reports",
    columns=[
        sc.ColumnInfo("master_entity", "text"),
        sc.ColumnInfo("Highest Injury Severity Alleged", "text"),
    ],
    value_samples={"master_entity": ["Cruise", "Waymo"]},
)

VALID_SQL = "SELECT master_entity FROM treated_incident_reports"


class FakeData:
    def __init__(self, *, schema_raises=False, rows=None):
        self._schema_raises = schema_raises
        self._rows = rows if rows is not None else [{"master_entity": "Waymo"}]

    async def schema_card(self):
        if self._schema_raises:
            raise RuntimeError("readonly pool down")
        return CARD

    async def validate(self, sql):
        return v.validate_static(sql)

    async def execute(self, sql):
        return list(self._rows)


class FakeModel:
    def __init__(self, *, sql=VALID_SQL):
        self._sql = sql

    def author(self, system, user):
        return self._sql


def _override(data, model, guard=None):
    app.dependency_overrides[get_nlsql_data] = lambda: data
    app.dependency_overrides[get_sql_model] = lambda: model
    app.dependency_overrides[get_nlsql_budget_guard] = lambda: guard or InMemoryBudgetGuard()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


# --- GET /nlsql/schema ------------------------------------------------------


def test_schema_returns_column_dictionary():
    _override(FakeData(), FakeModel())
    r = client.get("/nlsql/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["table"] == "treated_incident_reports"
    names = [c["name"] for c in body["columns"]]
    assert "master_entity" in names
    # raw-vs-clean flag + the quoted identifier are surfaced for the page.
    raw_col = next(c for c in body["columns"] if c["name"] == "Highest Injury Severity Alleged")
    assert raw_col["raw"] is True
    assert raw_col["identifier"] == '"Highest Injury Severity Alleged"'
    assert body["value_samples"]["master_entity"] == ["Cruise", "Waymo"]


def test_schema_degrades_when_db_unreachable():
    _override(FakeData(schema_raises=True), FakeModel())
    r = client.get("/nlsql/schema")
    assert r.status_code == 200
    assert r.json()["available"] is False


# --- POST /nlsql/query ------------------------------------------------------


def test_query_happy_path_returns_sql_and_rows():
    _override(FakeData(rows=[{"master_entity": "Waymo"}, {"master_entity": "Cruise"}]), FakeModel())
    r = client.post("/nlsql/query", json={"question": "list companies"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is False
    assert body["row_count"] == 2
    assert "treated_incident_reports" in body["sql"]


def test_query_never_500s_on_bad_model():
    # Model only ever returns DML -> validator rejects every attempt -> fallback.
    _override(FakeData(), FakeModel(sql="DROP TABLE treated_incident_reports"))
    r = client.post("/nlsql/query", json={"question": "delete everything"})
    assert r.status_code == 200
    assert r.json()["fallback"] is True


def test_query_over_length_is_rejected():
    _override(FakeData(), FakeModel())
    r = client.post("/nlsql/query", json={"question": "x" * 501})
    assert r.status_code == 422


def test_query_budget_tripped_degrades_to_fallback():
    _override(FakeData(), FakeModel(), guard=InMemoryBudgetGuard(daily_limit_usd=0.0))
    r = client.post("/nlsql/query", json={"question": "list companies"})
    assert r.status_code == 200
    assert r.json()["fallback"] is True
