"""Tests for the NL→Cypher execute-observe-repair agent (plan P3, U15).

The fallback + repair edges are the contract, so they're pinned hardest — plus
the two P3-specific ones: graph-unreachable is a first-class degrade (zero
model calls, budget untouched) and the real seam always executes read-mode.
The model, the graph seam, and validation-via-real-static-gate are all
in-memory: no network, no key, no Neo4j.
"""

from __future__ import annotations

from app.kgquery.agent import Neo4jKgData, run_kg_query
from app.kgquery.validate import validate_static
from app.nlsql.budget import InMemoryBudgetGuard
from tests.test_kgquery_graph_card import make_card

CARD = make_card()

VALID_CYPHER = (
    "MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle) RETURN c.name AS company, count(v) AS n"
)
ROWS = [{"company": "Waymo", "n": 3}, {"company": "Cruise", "n": 2}]


class FakeKgData:
    """In-memory graph seam. Validation uses the *real* static validator with
    the shared card fixture; execution returns canned rows, raises, or returns
    empty per construction. ``ping`` raises when built unreachable."""

    def __init__(self, *, rows=ROWS, execute_error=False, empty=False, unreachable=False):
        self._rows = rows
        self._execute_error = execute_error
        self._empty = empty
        self._unreachable = unreachable
        self.executed: list[str] = []
        self.pings = 0

    def graph_card(self):
        return CARD

    async def ping(self):
        self.pings += 1
        if self._unreachable:
            raise RuntimeError("ServiceUnavailable")

    async def validate(self, cypher):
        return validate_static(
            cypher,
            allowed_labels=CARD.allowed_labels,
            allowed_relationships=CARD.allowed_relationships,
        )

    async def execute(self, cypher):
        self.executed.append(cypher)
        if self._execute_error:
            raise RuntimeError("Neo.ClientError.Statement.SyntaxError")
        if self._empty:
            return []
        return list(self._rows)


class FakeCypherModel:
    """Returns queued Cypher strings in order (or raises). Records call count."""

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
        return VALID_CYPHER


# --- happy path -------------------------------------------------------------


async def test_valid_cypher_first_try_executes():
    model = FakeCypherModel(responses=[VALID_CYPHER])
    data = FakeKgData()
    result = await run_kg_query("companies by incidents", data=data, model=model)
    assert result["fallback"] is False
    assert result["graph_available"] is True
    assert result["iterations"] == 1
    assert result["row_count"] == 2
    assert "OPERATED_BY" in result["cypher"]
    # The validator injected the default LIMIT into the executed statement.
    assert "LIMIT" in data.executed[0]


# --- self-correction --------------------------------------------------------


async def test_invalid_then_valid_repairs():
    # First author returns a write (rejected by the validator), second is valid.
    model = FakeCypherModel(responses=["MATCH (n) DETACH DELETE n", VALID_CYPHER])
    data = FakeKgData()
    result = await run_kg_query("q", data=data, model=model)
    assert result["fallback"] is False
    assert result["iterations"] == 2
    assert result["row_count"] == 2
    statuses = [a["status"] for a in result["attempts"]]
    assert statuses == ["invalid", "valid"]


async def test_execution_error_then_valid_repairs():
    model = FakeCypherModel(responses=[VALID_CYPHER, VALID_CYPHER])

    class FlakyData(FakeKgData):
        def __init__(self):
            super().__init__()
            self._first = True

        async def execute(self, cypher):
            self.executed.append(cypher)
            if self._first:
                self._first = False
                raise RuntimeError("Neo.ClientError.Statement.SyntaxError")
            return list(ROWS)

    result = await run_kg_query("q", data=FlakyData(), model=model)
    assert result["fallback"] is False
    assert result["iterations"] == 2
    assert result["row_count"] == 2


# --- empty-result reconsideration -------------------------------------------


async def test_empty_result_reconsiders_once_then_accepts():
    model = FakeCypherModel(responses=[VALID_CYPHER, VALID_CYPHER])
    data = FakeKgData(empty=True)
    result = await run_kg_query("q", data=data, model=model)
    assert result["fallback"] is False
    assert result["row_count"] == 0
    assert result["iterations"] == 2
    assert model.calls == 2


async def test_refusal_contract_skips_reconsider():
    # The prompt's can't-answer contract is deliberately empty — accept it in
    # one iteration, don't burn a paid call second-guessing it.
    model = FakeCypherModel(responses=["RETURN NULL LIMIT 0"])
    result = await run_kg_query("q", data=FakeKgData(empty=True), model=model)
    assert result["fallback"] is False
    assert result["row_count"] == 0
    assert result["iterations"] == 1
    assert model.calls == 1


# --- graph-unreachable degrade (the P3-specific edge) -------------------------


async def test_graph_unreachable_degrades_without_model_call():
    model = FakeCypherModel(responses=[VALID_CYPHER])
    guard = InMemoryBudgetGuard(daily_limit_usd=100.0)
    data = FakeKgData(unreachable=True)
    result = await run_kg_query("q", data=data, model=model, guard=guard)
    assert result["fallback"] is True
    assert result["graph_available"] is False
    assert "unreachable" in result["message"].lower()
    assert model.calls == 0  # zero model calls
    assert guard.spent() == 0.0  # budget untouched
    assert data.executed == []


# --- error / budget / bound -------------------------------------------------


async def test_model_unavailable_falls_back():
    model = FakeCypherModel(raises=True)
    guard = InMemoryBudgetGuard(daily_limit_usd=100.0)
    result = await run_kg_query("q", data=FakeKgData(), model=model, guard=guard)
    assert result["fallback"] is True
    assert result["graph_available"] is True  # the graph is fine; the model isn't
    assert "unavailable" in result["message"].lower()
    assert result["iterations"] == 0
    # The reservation was released — no spend recorded for a call that didn't bill.
    assert guard.spent() == 0.0


async def test_budget_tripped_degrades_before_any_call():
    model = FakeCypherModel(responses=[VALID_CYPHER])
    guard = InMemoryBudgetGuard(daily_limit_usd=0.0)  # nothing fits
    result = await run_kg_query("q", data=FakeKgData(), model=model, guard=guard)
    assert result["fallback"] is True
    assert model.calls == 0  # never reached the paid call
    assert "busy" in result["message"].lower()


async def test_never_valid_stops_at_max_iterations():
    model = FakeCypherModel(responses=["MATCH (n) DETACH DELETE n"] * 5)
    result = await run_kg_query("q", data=FakeKgData(), model=model, max_iterations=3)
    assert result["fallback"] is True
    assert result["iterations"] == 3
    assert model.calls == 3  # bounded


async def test_result_shape_has_all_keys():
    result = await run_kg_query("q", data=FakeKgData(), model=FakeCypherModel())
    assert set(result) >= {
        "question",
        "cypher",
        "rows",
        "row_count",
        "iterations",
        "fallback",
        "attempts",
        "message",
        "graph_available",
    }


# --- the read-mode floor (the seam's contract) ---------------------------------


class StubDriver:
    """Captures every execute_query call so the test can assert read routing."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.verified = 0

    def verify_connectivity(self):
        self.verified += 1

    def execute_query(self, query, **kwargs):
        self.calls.append((query, kwargs))

        class _Result:
            records = []

        return _Result()


async def test_real_seam_always_executes_read_mode():
    import neo4j

    driver = StubDriver()
    data = Neo4jKgData(driver_getter=lambda: driver)
    await data.ping()
    await data.explain("MATCH (n:Incident) RETURN n LIMIT 1")
    await data.execute("MATCH (n:Incident) RETURN n LIMIT 1")
    assert driver.verified == 1
    assert len(driver.calls) == 2
    assert driver.calls[0][0].startswith("EXPLAIN ")
    for _query, kwargs in driver.calls:
        assert kwargs.get("routing_") == neo4j.RoutingControl.READ
