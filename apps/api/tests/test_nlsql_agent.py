"""Tests for the text-to-SQL execute-observe-repair agent (plan P1, U4).

The fallback + repair edges are the contract, so they're pinned hardest. The
model, the data layer, and the validator-via-fake are all in-memory: no network,
no key, no Postgres. The real validator runs inside the fake data layer so the
loop is exercised against genuine validation logic.
"""

from __future__ import annotations

from app.derived.budget import InMemoryBudgetGuard
from app.nlsql import schema_card as sc
from app.nlsql import validate as v
from app.nlsql.agent import run_sql_query

CARD = sc.SchemaCard(
    table="treated_incident_reports",
    columns=[
        sc.ColumnInfo("master_entity", "text"),
        sc.ColumnInfo("Highest Injury Severity Alleged", "text"),
    ],
    value_samples={"master_entity": ["Cruise", "Waymo"]},
)

VALID_SQL = "SELECT master_entity FROM treated_incident_reports"
ROWS = [{"master_entity": "Waymo"}, {"master_entity": "Cruise"}]


class FakeSqlData:
    """In-memory data seam. Validation uses the *real* static validator;
    execution returns canned rows, raises, or returns empty per construction."""

    def __init__(self, *, rows=ROWS, execute_error=False, empty=False):
        self._rows = rows
        self._execute_error = execute_error
        self._empty = empty
        self.executed: list[str] = []

    async def schema_card(self):
        return CARD

    async def validate(self, sql):
        return v.validate_static(sql)

    async def execute(self, sql):
        self.executed.append(sql)
        if self._execute_error:
            raise RuntimeError("asyncpg.UndefinedColumnError")
        if self._empty:
            return []
        return list(self._rows)


class FakeSqlModel:
    """Returns queued SQL strings in order (or raises). Records call count."""

    def __init__(self, *, responses=None, raises=False):
        self._responses = list(responses or [])
        self._raises = raises
        self.calls = 0

    def author(self, system, user):
        self.calls += 1
        if self._raises:
            raise RuntimeError("LLM timeout")
        if self._responses:
            return self._responses.pop(0)
        return VALID_SQL


# --- happy path -------------------------------------------------------------


async def test_valid_sql_first_try_executes():
    model = FakeSqlModel(responses=[VALID_SQL])
    data = FakeSqlData()
    result = await run_sql_query("companies by name", data=data, model=model)
    assert result["fallback"] is False
    assert result["iterations"] == 1
    assert result["row_count"] == 2
    assert "treated_incident_reports" in result["sql"]


# --- self-correction --------------------------------------------------------


async def test_invalid_then_valid_repairs():
    # First author returns DML (rejected by the validator), second returns a SELECT.
    model = FakeSqlModel(responses=["DROP TABLE treated_incident_reports", VALID_SQL])
    data = FakeSqlData()
    result = await run_sql_query("q", data=data, model=model)
    assert result["fallback"] is False
    assert result["iterations"] == 2
    assert result["row_count"] == 2
    # The attempts trace shows the rejected first try then the valid one.
    statuses = [a["status"] for a in result["attempts"]]
    assert statuses == ["invalid", "valid"]


async def test_db_error_then_valid_repairs():
    # Validates fine but the first execution errors; the model re-authors and the
    # second execution (different data layer state) succeeds.
    model = FakeSqlModel(responses=[VALID_SQL, VALID_SQL])

    class FlakyData(FakeSqlData):
        def __init__(self):
            super().__init__()
            self._first = True

        async def execute(self, sql):
            self.executed.append(sql)
            if self._first:
                self._first = False
                raise RuntimeError("asyncpg.UndefinedColumnError")
            return list(ROWS)

    result = await run_sql_query("q", data=FlakyData(), model=model)
    assert result["fallback"] is False
    assert result["iterations"] == 2
    assert result["row_count"] == 2


# --- empty-result reconsideration -------------------------------------------


async def test_empty_result_reconsiders_once_then_accepts():
    model = FakeSqlModel(responses=[VALID_SQL, VALID_SQL])
    data = FakeSqlData(empty=True)
    result = await run_sql_query("q", data=data, model=model)
    # One reconsider iteration, then accept the empty result (not a fallback).
    assert result["fallback"] is False
    assert result["row_count"] == 0
    assert result["iterations"] == 2
    assert model.calls == 2


# --- error / budget / bound -------------------------------------------------


async def test_model_unavailable_falls_back():
    model = FakeSqlModel(raises=True)
    guard = InMemoryBudgetGuard(daily_limit_usd=100.0)
    result = await run_sql_query("q", data=FakeSqlData(), model=model, guard=guard)
    assert result["fallback"] is True
    assert "unavailable" in result["message"].lower()
    assert result["iterations"] == 0
    # The reservation was released — no spend recorded for a call that didn't bill.
    assert guard.spent() == 0.0


async def test_budget_tripped_degrades_before_any_call():
    model = FakeSqlModel(responses=[VALID_SQL])
    guard = InMemoryBudgetGuard(daily_limit_usd=0.0)  # nothing fits
    result = await run_sql_query("q", data=FakeSqlData(), model=model, guard=guard)
    assert result["fallback"] is True
    assert model.calls == 0  # never reached the paid call
    assert "busy" in result["message"].lower()


async def test_never_valid_stops_at_max_iterations():
    model = FakeSqlModel(responses=["DROP TABLE treated_incident_reports"] * 5)
    result = await run_sql_query("q", data=FakeSqlData(), model=model, max_iterations=3)
    assert result["fallback"] is True
    assert result["iterations"] == 3
    assert model.calls == 3  # bounded


async def test_schema_card_failure_falls_back_without_calling_model():
    class BrokenData(FakeSqlData):
        async def schema_card(self):
            raise RuntimeError("readonly pool down")

    model = FakeSqlModel(responses=[VALID_SQL])
    result = await run_sql_query("q", data=BrokenData(), model=model)
    assert result["fallback"] is True
    assert model.calls == 0


async def test_result_shape_has_all_keys():
    result = await run_sql_query("q", data=FakeSqlData(), model=FakeSqlModel())
    assert set(result) >= {
        "question",
        "sql",
        "rows",
        "row_count",
        "iterations",
        "fallback",
        "attempts",
        "message",
    }
