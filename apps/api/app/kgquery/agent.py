"""NL→Cypher agent with an execute-observe-repair loop (plan P3, U15).

P1's loop shape transferred to the graph: assemble the graph card, ask the
model to author one read-only Cypher statement, validate it structurally +
via EXPLAIN, execute it in a **read-access-mode transaction**, and — on a
validation failure, a Cypher error, or an implausible empty result — feed the
observation back and repair, bounded by ``max_iterations`` and the budget guard.

    assemble_context --> generate_cypher --> validate --> execute --> respond
            |                  |  ^            |  |          | |
            |                  |  +--- repair--+  +-- repair-+ |  (iters < max)
            v                  v                                v
        fallback <------------(model error / budget / exhausted)

Two things differ from ``nlsql/agent.py``, both deliberate:

- **The safety floor is the read-mode transaction, not a credential.** Neo4j
  Community Edition has no role management, so every execution path goes
  through ``execute_query(routing_=READ)`` — the server rejects any write at
  runtime regardless of what slipped past the static validator.
- **Graph-unreachable is a first-class degrade, not an error.** The graph is
  rebuildable-not-authoritative (Railway restart, TCP proxy toggled off,
  instance down are all expected states); the agent returns
  ``{graph_available: false, ...}`` without spending a model call.

Key hygiene mirrors ``db.py``'s sanitized degrade: credentials are read at
call time, LLM/driver exceptions are swallowed without logging the key, the
password, or raw payloads, and the noisy client loggers are pinned to WARNING.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from .graph_card import GraphCard, load_graph_card
from .validate import ValidationResult, validate_cypher

logger = logging.getLogger(__name__)

for _name in ("langgraph", "langchain", "langchain_core", "anthropic", "httpx", "neo4j"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# High-frequency structural call pins the same model family as nlsql/derived
# (KTD-7). Override per-deploy via ANTHROPIC_MODEL.
DEFAULT_MODEL = "claude-haiku-4-5"

# Bound on author attempts — the loop's hard stop (plan: ~3).
MAX_ITERATIONS = 3

_FALLBACK_MESSAGE = "Couldn't answer that from the graph — try rephrasing."
_LLM_ERROR_MESSAGE = "The graph-query service is unavailable right now."
_BUDGET_MESSAGE = "The graph-query service is busy right now — try again later."
GRAPH_DOWN_MESSAGE = "The knowledge graph is unreachable right now — try again later."

SYSTEM_PROMPT = (
    "You author a single read-only Cypher query over a Neo4j knowledge graph "
    "of autonomous-vehicle crash incidents.\n"
    "Rules:\n"
    "  - Return ONLY the Cypher: one read-only statement, no prose, no "
    "explanation, no markdown fences, no trailing semicolon.\n"
    "  - Read-only: never CREATE/MERGE/DELETE/SET/REMOVE/FOREACH/LOAD CSV, "
    "and never CALL any procedure.\n"
    "  - Use only the node labels, relationship types, and connection patterns "
    "in the graph card below. Every node has `name`; use it to display and "
    "filter entities.\n"
    "  - If the question cannot be answered with these labels and "
    "relationships, return exactly: RETURN NULL LIMIT 0\n"
)


# The refusal contract from SYSTEM_PROMPT, matched loosely (case/whitespace,
# and the trailing semicolon models add — the validator tolerates it, so the
# refusal check must too or an honest refusal burns a reconsider call).
_REFUSAL_CYPHER_RE = re.compile(r"^returnnulllimit0$")


def is_refusal_cypher(cypher: str | None) -> bool:
    """True when ``cypher`` is the prompt's can't-answer contract (RETURN NULL LIMIT 0)."""
    return bool(_REFUSAL_CYPHER_RE.match(re.sub(r"[\s;]+", "", cypher or "").lower()))


class CypherModel(Protocol):
    """The injected model seam: (system, user) -> a single Cypher string."""

    def author(self, system: str, user: str) -> str: ...


class KgData(Protocol):
    """The injected graph seam (real impl: :class:`Neo4jKgData`).

    The contract every implementation must honor: **all** graph access —
    ``ping``, EXPLAIN inside ``validate``, and ``execute`` — runs in
    read-access-mode; ``ping`` raises when the graph is unreachable.
    """

    def graph_card(self) -> GraphCard: ...

    async def ping(self) -> None: ...

    async def validate(self, cypher: str) -> ValidationResult: ...

    async def execute(self, cypher: str) -> list[dict[str, Any]]: ...


# --- prompt building ----------------------------------------------------------


def build_user_prompt(
    question: str,
    card: GraphCard,
    *,
    examples: list[tuple[str, str]] | None = None,
    prior_cypher: str | None = None,
    observation: str | None = None,
) -> str:
    """Assemble the grounding context for one author attempt.

    On a repair iteration ``prior_cypher`` + ``observation`` (the Cypher error
    or the empty-result note) are appended so the model can see what went wrong.
    """
    parts = ["Graph card:", card.render(), ""]
    for ex_q, ex_cypher in examples or []:
        parts.append(f"Question: {ex_q}\nCypher: {ex_cypher}\n")
    parts.append(f"Question: {question}")
    if prior_cypher is not None:
        parts.append("")
        parts.append("Your previous attempt:")
        parts.append(prior_cypher)
        parts.append(f"It did not work: {observation}")
        parts.append("Return a corrected single read-only Cypher statement.")
    parts.append("Cypher:")
    return "\n".join(parts)


class ClaudeCypherModel:
    """Production :class:`CypherModel` backed by the Anthropic SDK.

    Constructed lazily so importing this module (and the test suite) never
    needs a key or network; a missing key raises on first ``author`` and the
    graph degrades to fallback.
    """

    def __init__(self, *, model: str | None = None, client: Any = None) -> None:
        self._model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
        return self._client

    def author(self, system: str, user: str) -> str:
        resp = self._ensure_client().messages.create(
            model=self._model,
            max_tokens=512,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()


# --- real read-mode graph seam --------------------------------------------------

NEO4J_ENV = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")

_DRIVER: Any = None
_DRIVER_LOCK = threading.Lock()


def get_neo4j_driver() -> Any:
    """Lazy singleton neo4j driver from the ``NEO4J_*`` env contract.

    Same env vars ``ontology/graph_load.py`` reads (private-network URI on
    Railway, the TCP-proxy address for local dev). A missing var raises a
    one-line setup hint pointing at the stack doc, never a raw traceback.
    """
    global _DRIVER
    if _DRIVER is not None:
        return _DRIVER
    with _DRIVER_LOCK:
        if _DRIVER is None:
            uri = os.environ.get("NEO4J_URI")
            username = os.environ.get("NEO4J_USERNAME")
            password = os.environ.get("NEO4J_PASSWORD")
            missing = [
                n for n, v in zip(NEO4J_ENV, (uri, username, password), strict=True) if not v
            ]
            if missing:
                raise RuntimeError(
                    f"{', '.join(missing)} not set. Point them at the Railway Neo4j "
                    "service (see docs/conventions/stack.md, 'Knowledge-graph queries')."
                )
            import neo4j

            # Tight timeouts so an unreachable graph degrades in seconds, not
            # the driver defaults' 30s connect + 30s retry window — /kg page
            # loads call /kgquery/status every render and must not hang on the
            # down-graph path. Railway private-network connects are millisecond
            # -fast and the queries are small reads, so 5s is generous.
            _DRIVER = neo4j.GraphDatabase.driver(
                uri,
                auth=(username, password),
                connection_timeout=5.0,
                max_transaction_retry_time=5.0,
            )
    return _DRIVER


def _jsonable(value: Any) -> Any:
    """Coerce neo4j values (dates, nodes-as-dicts, …) to JSON-safe primitives."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return str(value)


class Neo4jKgData:
    """Live graph seam. Every graph touch — ping, EXPLAIN, execute — runs
    ``execute_query(routing_=READ)``: the read-access-mode transaction is the
    safety floor (CE has no role management), so a write that somehow passed
    the static validator is still rejected by the server at runtime.
    Tests do not use this class against a live graph — they stub the driver."""

    def __init__(self, *, driver_getter=get_neo4j_driver) -> None:
        self._driver_getter = driver_getter

    def graph_card(self) -> GraphCard:
        return load_graph_card()

    def _run_read(self, cypher: str) -> list[dict[str, Any]]:
        import neo4j

        driver = self._driver_getter()
        result = driver.execute_query(cypher, routing_=neo4j.RoutingControl.READ)
        return [{k: _jsonable(v) for k, v in record.data().items()} for record in result.records]

    async def ping(self) -> None:
        driver = self._driver_getter()
        await asyncio.to_thread(driver.verify_connectivity)

    async def explain(self, cypher: str) -> None:
        await asyncio.to_thread(self._run_read, f"EXPLAIN {cypher}")

    async def validate(self, cypher: str) -> ValidationResult:
        return await validate_cypher(cypher, explainer=self)

    async def execute(self, cypher: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._run_read, cypher)


# --- graph state ----------------------------------------------------------------


class AgentState(TypedDict, total=False):
    question: str
    data: KgData
    model: CypherModel
    guard: Any
    examples: list[tuple[str, str]]
    max_iterations: int

    card: GraphCard
    iterations: int
    reconsidered_empty: bool
    candidate_cypher: str | None
    validation: ValidationResult | None
    observation: str | None
    rows: list[dict[str, Any]] | None
    attempts: list[dict[str, Any]]

    fallback: bool
    fallback_message: str
    graph_available: bool
    result: dict[str, Any]


# --- nodes ------------------------------------------------------------------


async def assemble_context(state: AgentState) -> dict[str, Any]:
    """Load the card (local yaml) and ping the graph. Unreachable graph is a
    first-class degrade: no model call, no budget spend."""
    try:
        card = state["data"].graph_card()
    except Exception:  # noqa: BLE001 — a broken/missing schema is a service
        # problem, not a bad question: degrade like graph-down (no "try
        # rephrasing" hint, no model call), never a per-question fallback.
        logger.warning("kgquery: graph-card build failed; degrading without a model call")
        return {
            "fallback": True,
            "graph_available": False,
            "fallback_message": GRAPH_DOWN_MESSAGE,
        }
    try:
        await state["data"].ping()
    except Exception:  # noqa: BLE001 — never log the URI/credentials
        logger.warning("kgquery: graph unreachable; degrading without a model call")
        return {
            "fallback": True,
            "graph_available": False,
            "fallback_message": GRAPH_DOWN_MESSAGE,
        }
    return {"card": card, "iterations": 0, "attempts": [], "reconsidered_empty": False}


async def generate_cypher(state: AgentState) -> dict[str, Any]:
    """One model call to author (or repair) Cypher, gated by the budget guard."""
    guard = state.get("guard")
    reservation = None
    if guard is not None:
        reservation = await guard.reserve(guard.estimate_cost())
        if reservation is None:
            return {"fallback": True, "fallback_message": _BUDGET_MESSAGE}

    user = build_user_prompt(
        state["question"],
        state["card"],
        examples=state.get("examples"),
        prior_cypher=state.get("candidate_cypher"),
        observation=state.get("observation"),
    )
    try:
        cypher = await asyncio.to_thread(state["model"].author, SYSTEM_PROMPT, user)
    except Exception:  # noqa: BLE001 — never log the key or raw payload
        if guard is not None and reservation is not None:
            await guard.release(reservation)
        logger.warning("kgquery: model call failed; using fallback")
        return {"fallback": True, "fallback_message": _LLM_ERROR_MESSAGE}

    return {"candidate_cypher": (cypher or "").strip(), "iterations": state["iterations"] + 1}


async def validate_node(state: AgentState) -> dict[str, Any]:
    result = await state["data"].validate(state["candidate_cypher"] or "")
    attempts = state.get("attempts", [])
    attempts = attempts + [
        {
            "iteration": state["iterations"],
            "cypher": state["candidate_cypher"],
            "status": "valid" if result.ok else "invalid",
            "reason": result.reason,
        }
    ]
    if result.ok:
        return {"validation": result, "attempts": attempts, "observation": None}
    return {"validation": result, "attempts": attempts, "observation": result.reason}


async def execute_node(state: AgentState) -> dict[str, Any]:
    cypher = (state["validation"].normalized_cypher if state.get("validation") else None) or ""
    try:
        rows = await state["data"].execute(cypher)
    except Exception as exc:  # noqa: BLE001 — feed the error back, don't crash
        logger.warning("kgquery: execution failed; will repair or fall back")
        return {"rows": None, "observation": f"the query errored: {type(exc).__name__}"}
    return {"rows": rows}


async def respond(state: AgentState) -> dict[str, Any]:
    cypher = state["validation"].normalized_cypher if state.get("validation") else None
    rows = state.get("rows") or []
    return {
        "result": {
            "question": state["question"],
            "cypher": cypher,
            "rows": rows,
            "row_count": len(rows),
            "iterations": state.get("iterations", 0),
            "fallback": False,
            "attempts": state.get("attempts", []),
            "message": "",
            "graph_available": True,
        }
    }


async def fallback(state: AgentState) -> dict[str, Any]:
    return {
        "result": {
            "question": state["question"],
            "cypher": state.get("candidate_cypher"),
            "rows": [],
            "row_count": 0,
            "iterations": state.get("iterations", 0),
            "fallback": True,
            "attempts": state.get("attempts", []),
            "message": state.get("fallback_message", _FALLBACK_MESSAGE),
            "graph_available": state.get("graph_available", True),
        }
    }


# --- edges ------------------------------------------------------------------


def _max_iters(state: AgentState) -> int:
    return state.get("max_iterations", MAX_ITERATIONS)


def _route_after_assemble(state: AgentState) -> str:
    return "fallback" if state.get("fallback") else "generate_cypher"


def _route_after_generate(state: AgentState) -> str:
    return "fallback" if state.get("fallback") else "validate"


def _route_after_validate(state: AgentState) -> str:
    if state["validation"].ok:
        return "execute"
    # Invalid Cypher: repair if we still have iterations, else give up.
    return "generate_cypher" if state["iterations"] < _max_iters(state) else "fallback"


def _route_after_execute(state: AgentState) -> str:
    rows = state.get("rows")
    if rows is None:
        # Execution error — repair if iterations remain, else fall back.
        return "generate_cypher" if state["iterations"] < _max_iters(state) else "fallback"
    if (
        not rows
        and not is_refusal_cypher(state.get("candidate_cypher"))
        and not state.get("reconsidered_empty")
        and state["iterations"] < _max_iters(state)
    ):
        # Empty result: reconsider once (maybe an entity name was wrong), then
        # accept the empty answer rather than looping forever. The refusal
        # contract is *deliberately* empty — don't burn a paid call on it.
        return "reconsider_empty"
    return "respond"


async def reconsider_empty(state: AgentState) -> dict[str, Any]:
    """Mark the one allowed empty-result reconsideration and feed it back."""
    return {
        "reconsidered_empty": True,
        "observation": (
            "the query was valid but returned zero rows — reconsider whether a "
            "node name, label, or relationship direction was wrong or too narrow"
        ),
    }


def _build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("generate_cypher", generate_cypher)
    builder.add_node("validate", validate_node)
    builder.add_node("execute", execute_node)
    builder.add_node("reconsider_empty", reconsider_empty)
    builder.add_node("respond", respond)
    builder.add_node("fallback", fallback)

    builder.add_edge(START, "assemble_context")
    builder.add_conditional_edges(
        "assemble_context",
        _route_after_assemble,
        {"generate_cypher": "generate_cypher", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "generate_cypher",
        _route_after_generate,
        {"validate": "validate", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"execute": "execute", "generate_cypher": "generate_cypher", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "execute",
        _route_after_execute,
        {
            "respond": "respond",
            "reconsider_empty": "reconsider_empty",
            "generate_cypher": "generate_cypher",
            "fallback": "fallback",
        },
    )
    builder.add_edge("reconsider_empty", "generate_cypher")
    builder.add_edge("respond", END)
    builder.add_edge("fallback", END)
    return builder.compile()


_GRAPH = _build_graph()


async def run_kg_query(
    question: str,
    *,
    data: KgData,
    model: CypherModel,
    guard: Any = None,
    examples: list[tuple[str, str]] | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> dict[str, Any]:
    """Run the NL→Cypher graph. Always returns a renderable result dict:

    ``{question, cypher, rows, row_count, iterations, fallback, attempts,
    message, graph_available}``.

    Never raises on bad model output or graph errors — failures route to the
    ``fallback`` node, and an unreachable graph comes back as
    ``graph_available=False`` without any model call. ``guard`` (optional)
    enforces a daily USD budget; omit it to run without gating (CLI + tests).
    """
    final = await _GRAPH.ainvoke(
        {
            "question": question or "",
            "data": data,
            "model": model,
            "guard": guard,
            "examples": examples,
            "max_iterations": max_iterations,
        }
    )
    return final["result"]


__all__ = [
    "DEFAULT_MODEL",
    "GRAPH_DOWN_MESSAGE",
    "MAX_ITERATIONS",
    "ClaudeCypherModel",
    "CypherModel",
    "KgData",
    "Neo4jKgData",
    "build_user_prompt",
    "get_neo4j_driver",
    "is_refusal_cypher",
    "run_kg_query",
]
