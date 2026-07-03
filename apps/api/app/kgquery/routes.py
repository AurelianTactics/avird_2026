"""KG-query routes (P3 web delivery, U17).

Two routes exposing the NL→Cypher agent to the `/kg` page — the pattern P1/P2
converged on, planned up front this time:

- ``GET  /kgquery/status`` — graph availability + node/relationship counts +
  the graph card (labels / relationship types / patterns) for the page
  sidebar. Degrades to ``available=false`` without erroring — the card still
  renders (it comes from the committed yaml, not the live graph).
- ``POST /kgquery/ask`` — author + validate + read-mode execute + repair,
  returning the Cypher, the rows, and the repair trace. Never 500s: agent
  failures come back as ``fallback=true``, a down graph as
  ``graph_available=false`` (mirrors ``nlsql/routes.py``).

Every collaborator is an injected FastAPI dependency (graph seam, model,
budget guard) so tests run with fakes — no key, no Neo4j.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .agent import (
    GRAPH_DOWN_MESSAGE,
    ClaudeCypherModel,
    CypherModel,
    KgData,
    Neo4jKgData,
    run_kg_query,
)
from .budget import BudgetGuard, get_kgquery_budget_guard

router = APIRouter(prefix="/kgquery")

# Same input bound as the other paid NL surfaces — cap before any paid call.
MAX_QUESTION_CHARS = 500

# Both counts in one round trip (the status endpoint runs on every /kg page
# load); a failed execute doubles as the reachability probe, so no ping first.
# OPTIONAL MATCH keeps the row when the graph has nodes but no relationships.
_COUNTS_CYPHER = (
    "MATCH (n) WITH count(n) AS nodes "
    "OPTIONAL MATCH ()-[r]->() RETURN nodes, count(r) AS relationships"
)


class AskRequest(BaseModel):
    question: str = Field(default="", max_length=MAX_QUESTION_CHARS)


def get_kg_data() -> KgData:
    """FastAPI dependency for the read-mode graph seam. Tests override with a fake."""
    return Neo4jKgData()


def get_cypher_model() -> CypherModel:
    """FastAPI dependency for the model client. Tests override with a fake."""
    return ClaudeCypherModel()


@router.get("/status")
async def status(data: KgData = Depends(get_kg_data)) -> dict[str, Any]:
    """Graph availability + counts + the card for the page sidebar.

    The card comes from the committed schema yaml, so it renders even when the
    graph is down; only ``available``/counts reflect the live instance."""
    try:
        card = data.graph_card()
        card_payload = {
            "labels": sorted(card.allowed_labels),
            "relationship_types": sorted(card.allowed_relationships),
            "patterns": [list(p) for p in card.patterns],
        }
    except Exception:  # noqa: BLE001 — page still renders with a notice
        card_payload = {"labels": [], "relationship_types": [], "patterns": []}

    try:
        rows = await data.execute(_COUNTS_CYPHER)
        row = rows[0] if rows else {}
        return {
            "available": True,
            "nodes": int(row.get("nodes") or 0),
            "relationships": int(row.get("relationships") or 0),
            "card": card_payload,
        }
    except Exception:  # noqa: BLE001 — graph down is a first-class degrade
        return {"available": False, "nodes": 0, "relationships": 0, "card": card_payload}


@router.post("/ask")
async def ask(
    body: AskRequest,
    data: KgData = Depends(get_kg_data),
    model: CypherModel = Depends(get_cypher_model),
    guard: BudgetGuard = Depends(get_kgquery_budget_guard),
) -> dict[str, Any]:
    """Run the NL→Cypher agent. Always returns a renderable result dict
    ``{question, cypher, rows, row_count, iterations, fallback, attempts,
    message, graph_available}``; never 500s (agent failures surface as
    ``fallback=true``, a down graph as ``graph_available=false``)."""
    try:
        return await run_kg_query(body.question, data=data, model=model, guard=guard)
    except Exception:  # noqa: BLE001 — the never-500 contract
        return {
            "question": body.question,
            "cypher": None,
            "rows": [],
            "row_count": 0,
            "iterations": 0,
            "fallback": True,
            "attempts": [],
            "message": GRAPH_DOWN_MESSAGE,
            "graph_available": False,
        }
