"""Derived view routes (U3 + U6).

Three read-only routes over the treated canonical rows:

- ``GET /derived/heatmaps`` — the two heatmap matrices, default (unfiltered) or
  filtered by explicit ``entity`` / ``state`` / ``severity`` query params.
  Deterministic and LLM-free (plan KTD 4): the default page render never incurs
  LLM latency, cost, or failure modes.
- ``GET /derived/redaction`` — the static redacted-narrative breakdown over all
  canonical rows; ignores filters (plan KTD 9).
- ``POST /derived/query`` — the natural-language path (U6); runs the LangGraph
  agent and always returns a renderable result (never 500s on a bad query).

The candidate values from query params are resolved through the U1 allow-list
(fed by `fetch_known_values`) exactly like the NL path — fixed identifiers,
parameterized values, raw input never interpolated (plan KTD 3).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..data import IncidentData, get_incident_data
from .agent import ClaudeFilterModel, FilterModel, run_query
from .aggregate import build_heatmaps, filter_rows_by_severity, redaction_breakdown
from .budget import BudgetGuard, get_budget_guard
from .filters import DerivedFilter, resolve

router = APIRouter(prefix="/derived")


class QueryRequest(BaseModel):
    # First POST on the public surface: bound the body before any agent/LLM call.
    text: str = Field(default="", max_length=500)


def get_filter_model() -> FilterModel:
    """FastAPI dependency for the NL model client. Tests override with a fake."""
    return ClaudeFilterModel()


async def _heatmaps_for_filter(data: IncidentData, raw: dict[str, Any]) -> dict[str, Any]:
    """Resolve candidate values, fetch + aggregate, return the heatmap payload.

    Shared by the deterministic GET route (query-param candidates) — the same
    aggregation core the agent uses, so the default page and a filter run one
    code path (plan KTD 1, KTD 4).
    """
    known = await data.fetch_known_values()
    resolution = resolve(raw, known_entities=known["entities"], known_states=known["states"])
    rows = await data.fetch_derived_rows(resolution.filter)
    rows = filter_rows_by_severity(rows, resolution.filter.severity_bucket)
    payload = build_heatmaps(rows)
    payload["applied_filter"] = resolution.filter.as_dict()
    return payload


@router.get("/heatmaps")
async def heatmaps(
    entity: str | None = None,
    state: str | None = None,
    severity: str | None = None,
    data: IncidentData = Depends(get_incident_data),
) -> dict[str, Any]:
    # No params -> empty raw -> unfiltered default. Unknown candidates resolve
    # to nothing for that dimension and are simply dropped (200, not an error).
    return await _heatmaps_for_filter(
        data, {"entity": entity, "state": state, "severity": severity}
    )


@router.get("/redaction")
async def redaction(
    data: IncidentData = Depends(get_incident_data),
) -> dict[str, Any]:
    # Static, unfiltered: redaction is grouped by entity and collapses under a
    # marquee filter, so it lives outside the NL surface (plan KTD 9).
    rows = await data.fetch_derived_rows(DerivedFilter())
    return {"redaction": redaction_breakdown(rows)}


@router.post("/query")
async def query(
    body: QueryRequest,
    data: IncidentData = Depends(get_incident_data),
    model: FilterModel = Depends(get_filter_model),
    guard: BudgetGuard = Depends(get_budget_guard),
) -> dict[str, Any]:
    # Runs the agent graph (U5). Never 500s on a bad query: agent failures surface
    # as fallback=true with the default (unfiltered) matrices (plan KTD 4/KTD 5).
    # Same heatmap shape as GET /derived/heatmaps plus {fallback, message}.
    # `guard` enforces a daily USD cap on this public LLM surface (budget.py); over
    # the cap the agent degrades to the default view rather than erroring.
    return await run_query(body.text, data=data, model=model, guard=guard)
