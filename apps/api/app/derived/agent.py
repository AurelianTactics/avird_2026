"""LangGraph NL -> filter agent with default fallback (U5).

A small explicit graph maps free text to a validated `DerivedFilter` and the two
heatmap matrices. Every failure edge routes to a `default_view` node that returns
the unfiltered matrices with ``fallback=True`` — the route never raises on a bad
query (plan KTD 5). The "fall back to default" rule is therefore first-class and
independently testable, which is the whole point of using a graph over an inline
``try/except``.

    parse_intent --> validate_filter --> aggregate --> respond
         |                  |                |
         +------------------+----------------+
         (LLM error,        (nothing resolved /     (aggregate
          malformed JSON)    validation error)       failure)
                            |
                            v
                       default_view

The LLM is the only path to a filter — this is a learning project for the
LLM/LangGraph mechanics, so there is deliberately **no rules-based recovery**.
If the model is unavailable (no key, timeout, or malformed output) `parse_intent`
fails and the graph routes straight to `default_view`: the unfiltered matrices
plus a concise error message. Likewise if the model returns candidates but none
resolve to a known value. The single fallback is always "show the default."

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
from .budget import BudgetGuard
from .filters import DerivedFilter, resolve

logger = logging.getLogger(__name__)

# Pin noisy third-party loggers so DEBUG-level config logging can't leak the key.
for _name in ("langgraph", "langchain", "langchain_core", "anthropic", "httpx"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Latest Claude (skill default). Override per-deploy via ANTHROPIC_MODEL.
DEFAULT_MODEL = "claude-haiku-4-5"

# Default fallback note (validation/aggregation failure, or nothing resolved).
_FALLBACK_MESSAGE = "Couldn't apply that filter — showing all incidents."
# Shown when the LLM itself is unavailable/errored (no key, timeout, bad output).
_LLM_ERROR_MESSAGE = (
    "The natural-language query service is unavailable right now — showing all incidents."
)
# Shown when the daily NL-query budget is exhausted — degrade to the default view
# rather than erroring, so the page stays usable (KTD 5). See `budget.py`.
_BUDGET_MESSAGE = "The natural-language query service is busy right now — showing all incidents."

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
    # Optional daily-budget guard (the route injects the durable one; agent unit
    # tests run without it). When present, `parse_intent` reserves before the call.
    guard: Any
    candidate: dict[str, Any] | None
    parse_failed: bool
    fallback_message: str
    resolution: Any
    validate_failed: bool
    aggregate_failed: bool
    result: dict[str, Any]


# --- Nodes ------------------------------------------------------------------


async def parse_intent(state: AgentState) -> dict[str, Any]:
    """Single Claude call: NL -> candidate filter JSON. Blank text skips the LLM.

    On any LLM failure (no key, timeout, or non-JSON output) this routes straight
    to `default_view` — there is no rules-based recovery. The single fallback is
    the default view with a concise "service unavailable" note.

    When a budget `guard` is injected, the call is gated by a daily USD cap: the
    worst-case cost is reserved *before* the paid call (so concurrent requests
    can't all slip past the cap), kept if a paid call happens, and released if it
    doesn't. Over the cap we degrade to the default view, not an error (KTD 5).
    """
    text = (state.get("text") or "").strip()
    if not text:
        return {"candidate": {}, "parse_failed": False}

    guard = state.get("guard")
    reservation = None
    if guard is not None:
        reservation = await guard.reserve(guard.estimate_cost())
        if reservation is None:
            # Daily budget exhausted — show the default view with a budget note.
            return {"candidate": None, "parse_failed": True, "fallback_message": _BUDGET_MESSAGE}

    try:
        raw = await asyncio.to_thread(state["model"].propose, text)
    except Exception:  # noqa: BLE001 — never log the key or raw payload
        # The paid call didn't bill (no key / timeout) — free the reservation.
        if guard is not None and reservation is not None:
            await guard.release(reservation)
        logger.warning("NL query LLM call failed; using default view")
        return {"candidate": None, "parse_failed": True, "fallback_message": _LLM_ERROR_MESSAGE}

    # propose returned -> a paid call happened; keep the reservation even if the
    # output is unparseable (we were still billed for it).
    try:
        candidate = json.loads(raw)
        if not isinstance(candidate, dict):
            raise ValueError("model did not return a JSON object")
    except Exception:  # noqa: BLE001
        logger.warning("NL query returned malformed output; using default view")
        return {"candidate": None, "parse_failed": True, "fallback_message": _LLM_ERROR_MESSAGE}
    return {"candidate": candidate, "parse_failed": False}


async def validate_filter(state: AgentState) -> dict[str, Any]:
    """Resolve the LLM's candidate values against the data-layer allow-list (U1).

    Only reached when `parse_intent` succeeded, so ``candidate`` is always the
    model's parsed JSON object.
    """
    try:
        known = await state["data"].fetch_known_values()
        resolution = resolve(
            state["candidate"],
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
            "message": state.get("fallback_message", _FALLBACK_MESSAGE),
            **heatmaps,
        }
    }


async def respond(state: AgentState) -> dict[str, Any]:
    """Terminal node — the result is already assembled upstream."""
    return {}


# --- Edges ------------------------------------------------------------------


def _route_after_parse(state: AgentState) -> str:
    # LLM unavailable / malformed output -> default view (no rules-based recovery).
    return "default_view" if state.get("parse_failed") else "validate_filter"


def _route_after_validate(state: AgentState) -> str:
    if state.get("validate_failed"):
        return "default_view"
    resolution = state["resolution"]
    # The model proposed value(s) but none resolved to an allow-listed value -> the
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
    # Parse failure (LLM down / malformed) routes straight to the default view —
    # there is no rules-based recovery; the single fallback is "show the default."
    builder.add_conditional_edges(
        "parse_intent",
        _route_after_parse,
        {"validate_filter": "validate_filter", "default_view": "default_view"},
    )
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


async def run_query(
    text: str,
    *,
    data: IncidentData,
    model: FilterModel,
    guard: BudgetGuard | None = None,
) -> dict[str, Any]:
    """Run the NL-query graph. Always returns a renderable result dict:

    ``{applied_filter, fallback, message, contact_areas, pre_crash}``.

    `guard`, when provided, enforces the daily NL-query budget (see `budget.py`);
    omit it (the agent unit tests do) to run the graph with no budget gating.
    """
    final = await _GRAPH.ainvoke({"text": text or "", "data": data, "model": model, "guard": guard})
    return final["result"]


__all__ = ["ClaudeFilterModel", "DEFAULT_MODEL", "FilterModel", "run_query"]
