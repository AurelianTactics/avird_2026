"""Tests for the Cypher validator (P3, U14).

Every write/injection vector must come back ``ok=False`` with a human-readable
reason — never an exception. The allow-list vocabulary is the same fixture the
graph-card tests parse, proving the card→validator contract end to end.
"""

from __future__ import annotations

import pytest

from app.kgquery.validate import validate_cypher, validate_static
from tests.test_kgquery_graph_card import make_card

CARD = make_card()
LABELS = CARD.allowed_labels
RELS = CARD.allowed_relationships


def check(cypher: str):
    return validate_static(cypher, allowed_labels=LABELS, allowed_relationships=RELS)


VALID = "MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle) RETURN c.name, count(v) AS n"


# --- happy path ---------------------------------------------------------------


def test_valid_read_cypher_passes_and_gets_limit_injected():
    result = check(VALID)
    assert result.ok
    assert result.normalized_cypher.endswith("LIMIT 200")


def test_existing_limit_is_left_unchanged():
    result = check(VALID + " ORDER BY n DESC LIMIT 10")
    assert result.ok
    assert result.normalized_cypher.endswith("LIMIT 10")


def test_trailing_semicolon_is_tolerated():
    result = check(VALID + ";")
    assert result.ok
    assert ";" not in result.normalized_cypher


# --- write clauses --------------------------------------------------------------


@pytest.mark.parametrize(
    "cypher",
    [
        "MATCH (n) DETACH DELETE n",
        "MATCH (n:Incident) SET n.x = 1 RETURN n",
        "MERGE (:Company {name:'x'})",
        "CREATE (:Incident {name:'x'})",
        "MATCH (n:Incident) REMOVE n.name RETURN n",
        "FOREACH (x IN [1] | CREATE (:Incident))",
        "LOAD CSV FROM 'file:///x.csv' AS row RETURN row",
        "DROP CONSTRAINT incident_key_unique",
    ],
)
def test_write_clauses_rejected(cypher):
    result = check(cypher)
    assert result.ok is False
    assert result.reason  # human-readable, never empty


def test_write_keyword_inside_string_literal_does_not_false_trip():
    result = check("MATCH (i:Incident) WHERE i.name = 'driver failed to SET brake' RETURN i")
    assert result.ok


# --- CALL wholesale -------------------------------------------------------------


@pytest.mark.parametrize(
    "cypher",
    [
        "CALL db.labels()",
        "CALL apoc.load.json('x')",
        "MATCH (n:Incident) CALL { RETURN 1 } RETURN n",
    ],
)
def test_call_rejected_wholesale(cypher):
    result = check(cypher)
    assert result.ok is False
    assert "CALL" in result.reason


# --- allow-list -----------------------------------------------------------------


def test_unknown_label_rejected():
    result = check("MATCH (u:User) RETURN u")
    assert result.ok is False
    assert "User" in result.reason


def test_unknown_relationship_rejected():
    result = check("MATCH (:Incident)-[:HACKED_BY]->(:Company) RETURN 1")
    assert result.ok is False
    assert "HACKED_BY" in result.reason


def test_backticks_rejected():
    result = check("MATCH (n:`Weird Label`) RETURN n")
    assert result.ok is False
    assert "backtick" in result.reason


# --- statement chaining / degenerate input ---------------------------------------


def test_multi_statement_rejected():
    result = check("MATCH (n:Incident) RETURN n; MATCH (m:Vehicle) RETURN m")
    assert result.ok is False
    assert "single statement" in result.reason


@pytest.mark.parametrize("cypher", ["", "   ", ";", None])
def test_empty_input_rejected(cypher):
    result = validate_static(cypher, allowed_labels=LABELS, allowed_relationships=RELS)
    assert result.ok is False


# --- EXPLAIN seam ----------------------------------------------------------------


class FakeExplainer:
    def __init__(self, *, raises=False):
        self._raises = raises
        self.explained: list[str] = []

    async def explain(self, cypher: str) -> None:
        self.explained.append(cypher)
        if self._raises:
            raise RuntimeError("CypherSyntaxError")


async def test_explain_pass_returns_normalized_cypher():
    explainer = FakeExplainer()
    result = await validate_cypher(
        VALID, explainer=explainer, allowed_labels=LABELS, allowed_relationships=RELS
    )
    assert result.ok
    # EXPLAIN ran on the normalized (LIMIT-injected) statement.
    assert explainer.explained == [result.normalized_cypher]


async def test_syntax_error_fails_at_explain_with_reason():
    result = await validate_cypher(
        "MATCH (c:Company RETURN c",  # unbalanced paren passes no static rule
        explainer=FakeExplainer(raises=True),
        allowed_labels=LABELS,
        allowed_relationships=RELS,
    )
    assert result.ok is False
    assert "EXPLAIN failed" in result.reason


async def test_static_failure_skips_explain():
    explainer = FakeExplainer()
    result = await validate_cypher(
        "MATCH (n) DETACH DELETE n",
        explainer=explainer,
        allowed_labels=LABELS,
        allowed_relationships=RELS,
    )
    assert result.ok is False
    assert explainer.explained == []
