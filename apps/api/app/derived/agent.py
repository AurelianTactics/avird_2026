"""LangGraph NL -> filter agent with default fallback (U5).

A small explicit graph maps free text to a validated `DerivedFilter` and the two
heatmap matrices. Every failure edge routes to a `default_view` node that returns
the unfiltered matrices with ``fallback=True`` — the route never raises on a bad
query (plan KTD 5). The "fall back to default" rule is therefore first-class and
independently testable, which is the whole point of using a graph over an inline
``try/except``.

    parse_intent --> validate_filter --> aggregate --> respond
         |                  |                |
         +------------------+                |
         (parse failure no   |               |
          longer dead-ends)  +-- default_view +   (validate / aggregate failure)

When the LLM is unavailable (no key, timeout, or malformed output), `parse_intent`
sets ``candidate=None`` and `validate_filter` recovers deterministically via
`filters.heuristic_candidates` — keyword-scanning the raw text against the same
allow-list. So "only Waymo vehicles in Arizona" still filters with no model call;
only genuinely un-actionable text (nothing matches a known value) reaches
`default_view`. This is the "maybe filter by that" behavior over a silent
show-everything.

The model client is **injected** (`run_query(..., model=...)`) so tests run with a
fake returning canned JSON — no network, no key. Security boundary: the model only
proposes *candidate* values; `filters.resolve` validates them against the data
layer's allow-list, and aggregation uses parameterized SQL (plan KTD 3).

Key hygiene (mirrors `db.py`'s sanitized degrade): the key is read at call time by
the Anthropic SDK, LLM exceptions are swallowed without logging the key or the raw
exception payload, and the langchain/langgraph/anthropic/httpx loggers are pinned
to WARNING so DEBUG config logging cannot leak the credential.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from ..data import IncidentData
from .aggregate import build_heatmaps, filter_rows_by_severity
from .filters import DerivedFilter, heuristic_candidates, resolve

logger = logging.getLogger(__name__)

# Pin noisy third-party loggers so DEBUG-level config logging can't leak the key.
for _name in ("langgraph", "langchain", "langchain_core", "anthropic", "httpx"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Latest Claude (skill default). Override per-deploy via ANTHROPIC_MODEL.
DEFAULT_MODEL = "claude-opus-4-8"

_FALLBACK_MESSAGE = "Couldn't apply that filter — showing all incidents."

SYSTEM_PROMPT = (
    "You extract a structured filter from a user's natural-language request about "
    "autonomous-vehicle crash incidents. Return ONLY a compact JSON object with any "
    "of these optional keys:\n"
    '  - "entity":   a company/operator name (e.g. "Waymo", "Cruise")\n'
    '  - "state":    a US state name or 2-letter code (e.g. "Arizona" or "AZ")\n'
    '  - "severity": one of: Fatality, Serious, Moderate, Minor, No Injuries, Property\n'
    "Omit any key the user did not mention. If the request implies no filter, return {}. "
    "Output only the JSON object — no prose, no explanation, no markdown fences."
)


class FilterModel(Protocol):
    """The injected model seam: free text -> candidate filter JSON (a string)."""

    def propose(self, text: str) -> str: ...


class ClaudeFilterModel:
    """Production `FilterModel` backed by the Anthropic SDK.

    The client is constructed lazily on first use, so `ANTHROPIC_API_KEY` is read
    at call time (and a missing key raises here, caught by the graph's parse edge,
    degrading to the default view).
    """

    def __init__(self, *, model: str | None = None, client: Any = None) -> None:
        self._model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self._client

    def propose(self, text: str) -> str:
        resp = self._ensure_client().messages.create(
            model=self._model,
            max_tokens=256,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()


# --- Graph state ------------------------------------------------------------


class AgentState(TypedDict, total=False):
    text: str
    data: IncidentData
    model: FilterModel
    candidate: dict[str, Any] | None
    parse_failed: bool
    resolution: Any
    validate_failed: bool
    aggregate_failed: bool
    result: dict[str, Any]


# --- Nodes ------------------------------------------------------------------


async def parse_intent(state: AgentState) -> dict[str, Any]:
    """Single Claude call: NL -> candidate filter JSON. Blank text skips the LLM."""
    text = (state.get("text") or "").strip()
    if not text:
        return {"candidate": {}, "parse_failed": False}
    try:
        raw = await asyncio.to_thread(state["model"].propose, text)
        candidate = json.loads(raw)
        if not isinstance(candidate, dict):
            raise ValueError("model did not return a JSON object")
    except Exception:  # noqa: BLE001 — never log the key or raw payload
        logger.warning("NL query parse failed; using default view")
        return {"candidate": None, "parse_failed": True}
    return {"candidate": candidate, "parse_failed": False}


async def validate_filter(state: AgentState) -> dict[str, Any]:
    """Resolve candidate values against the data-layer allow-list (U1).

    When the LLM parse failed (``candidate is None``), recover deterministically
    by keyword-scanning the raw text against the same allow-list — the NL path
    degrades to filtering rather than silently showing everything.
    """
    try:
        known = await state["data"].fetch_known_values()
        candidate = state.get("candidate")
        if candidate is None:
            candidate = heuristic_candidates(
                state.get("text") or "",
                known_entities=known["entities"],
                known_states=known["states"],
            )
        resolution = resolve(
            candidate,
            known_entities=known["entities"],
            known_states=known["states"],
        )
    except Exception:  # noqa: BLE001
        logger.warning("filter validation failed; using default view")
        return {"resolution": None, "validate_failed": True}
    return {"resolution": resolution, "validate_failed": False}


async def aggregate(state: AgentState) -> dict[str, Any]:
    """Fetch canonical rows for the validated filter and build the matrices."""
    filt: DerivedFilter = state["resolution"].filter
    try:
        rows = await state["data"].fetch_derived_rows(filt)
        rows = filter_rows_by_severity(rows, filt.severity_bucket)
        heatmaps = build_heatmaps(rows)
    except Exception:  # noqa: BLE001
        logger.warning("aggregation failed; using default view")
        return {"aggregate_failed": True}
    return {
        "result": {
            "applied_filter": filt.as_dict(),
            "fallback": False,
            "message": "",
            **heatmaps,
        }
    }


async def default_view(state: AgentState) -> dict[str, Any]:
    """Unfiltered matrices + fallback flag. Never raises — the contract's floor."""
    try:
        rows = await state["data"].fetch_derived_rows(DerivedFilter())
        heatmaps = build_heatmaps(rows)
    except Exception:  # noqa: BLE001
        logger.warning("default-view aggregation failed; returning empty matrices")
        heatmaps = build_heatmaps([])
    return {
        "result": {
            "applied_filter": {},
            "fallback": True,
            "message": _FALLBACK_MESSAGE,
            **heatmaps,
        }
    }


async def respond(state: AgentState) -> dict[str, Any]:
    """Terminal node — the result is already assembled upstream."""
    return {}


# --- Edges ------------------------------------------------------------------


def _route_after_validate(state: AgentState) -> str:
    if state.get("validate_failed"):
        return "default_view"
    resolution = state["resolution"]
    # Parse failed and the deterministic recovery found nothing actionable -> the
    # user typed something we couldn't act on; show the default with a note.
    if state.get("parse_failed") and not resolution.resolved:
        return "default_view"
    # Something was proposed but nothing resolved to an allow-listed value -> the
    # query "failed" in the user's sense; show the default. An empty candidate
    # (genuine "show all") has no drops and proceeds to an unfiltered aggregate.
    if resolution.dropped and not resolution.resolved:
        return "default_view"
    return "aggregate"


def _route_after_aggregate(state: AgentState) -> str:
    return "default_view" if state.get("aggregate_failed") else "respond"


def _build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("parse_intent", parse_intent)
    builder.add_node("validate_filter", validate_filter)
    builder.add_node("aggregate", aggregate)
    builder.add_node("default_view", default_view)
    builder.add_node("respond", respond)

    builder.add_edge(START, "parse_intent")
    # Parse failure no longer dead-ends: validate_filter runs the deterministic
    # recovery, so a keyless/erroring LLM still yields a usable filter.
    builder.add_edge("parse_intent", "validate_filter")
    builder.add_conditional_edges(
        "validate_filter",
        _route_after_validate,
        {"aggregate": "aggregate", "default_view": "default_view"},
    )
    builder.add_conditional_edges(
        "aggregate",
        _route_after_aggregate,
        {"respond": "respond", "default_view": "default_view"},
    )
    builder.add_edge("default_view", "respond")
    builder.add_edge("respond", END)
    return builder.compile()


_GRAPH = _build_graph()


async def run_query(text: str, *, data: IncidentData, model: FilterModel) -> dict[str, Any]:
    """Run the NL-query graph. Always returns a renderable result dict:

    ``{applied_filter, fallback, message, contact_areas, pre_crash}``.
    """
    final = await _GRAPH.ainvoke({"text": text or "", "data": data, "model": model})
    return final["result"]


__all__ = ["ClaudeFilterModel", "DEFAULT_MODEL", "FilterModel", "run_query"]
