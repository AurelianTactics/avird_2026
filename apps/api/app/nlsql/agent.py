"""Text-to-SQL agent with an execute-observe-repair loop (plan P1, U4).

This is the reusable loop shape the whole progression builds on: the agent
assembles grounding context, asks the model to author a ``SELECT``, validates it
structurally, runs it on the **read-only** role, and — on a validation failure,
a DB error, or an implausible empty result — feeds the observation back and lets
the model repair, bounded by ``max_iterations`` and the budget guard.

    assemble_context --> generate_sql --> validate --> execute --> respond
            |                 |  ^           |  |          | |
            |                 |  +--- repair-+  +-- repair-+ |  (iters < max)
            v                 v                               v
        fallback <-----------(model error / budget / exhausted)

It mirrors ``derived/agent.py`` deliberately: an explicit graph so "what happens
when generation fails" is a first-class, independently testable edge, an injected
model ``Protocol`` (real Anthropic impl + a fake for tests), a budget reserve/
release around the paid call, and a single ``fallback`` node that never raises.
The difference from the bounded filter is altitude: here the model authors real
SQL, made safe by the read-only role + validator rather than an allow-list of
pre-shaped filters.

The model is the only path to SQL — there is no rules-based recovery. If it is
unavailable (no key, timeout, malformed) or the loop exhausts its iterations, the
graph routes to ``fallback``: a "couldn't answer" result that still carries the
last attempted SQL, so the learning surface can show what the model tried.

Key hygiene mirrors ``db.py``'s sanitized degrade: the key is read at call time,
LLM/DB exceptions are swallowed without logging the key or raw payload, and the
anthropic/httpx loggers are pinned to WARNING.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from .schema_card import SchemaCard, build_schema_card
from .validate import ValidationResult, validate_sql

logger = logging.getLogger(__name__)

for _name in ("langgraph", "langchain", "langchain_core", "anthropic", "httpx"):
    logging.getLogger(_name).setLevel(logging.WARNING)

# Latest Claude for the high-frequency structural call (KTD-7), matching the
# NL-query + debate defaults. Override per-deploy via ANTHROPIC_MODEL.
DEFAULT_MODEL = "claude-haiku-4-5"

# Bound on author attempts — the loop's hard stop (plan: ~3).
MAX_ITERATIONS = 3

_FALLBACK_MESSAGE = "Couldn't answer that from the data — try rephrasing."
_LLM_ERROR_MESSAGE = "The text-to-SQL service is unavailable right now."
_BUDGET_MESSAGE = "The text-to-SQL service is busy right now — try again later."

SYSTEM_PROMPT = (
    "You author a single read-only PostgreSQL query that answers the user's "
    "question about autonomous-vehicle crash incidents.\n"
    "Rules:\n"
    "  - Return ONLY the SQL: one SELECT statement, no prose, no explanation, "
    "no markdown fences, no trailing semicolon.\n"
    "  - Read-only: never write DDL or DML (no INSERT/UPDATE/DELETE/DROP/etc.).\n"
    "  - Use only the table and columns in the schema card below. Quote a column "
    "exactly as the card shows it (raw mixed-case columns need double quotes; "
    "clean snake_case columns do not).\n"
    "  - If the question cannot be answered from these columns, return exactly: "
    "SELECT NULL WHERE false\n"
)


# The refusal contract from SYSTEM_PROMPT, matched loosely: the validator may
# have injected a LIMIT into the normalized form, and sqlglot may parenthesize.
_REFUSAL_SQL_RE = re.compile(r"^selectnullwhere\(?false\)?(limit\d+)?$")


def is_refusal_sql(sql: str | None) -> bool:
    """True when ``sql`` is the prompt's can't-answer contract (SELECT NULL WHERE false)."""
    return bool(_REFUSAL_SQL_RE.match(re.sub(r"\s+", "", sql or "").lower()))


class SqlModel(Protocol):
    """The injected model seam: (system, user) -> a single SQL string."""

    def author(self, system: str, user: str) -> str:
        ...


class SqlData(Protocol):
    """The injected read-only data seam (real impl: :class:`NlSqlData`)."""

    async def schema_card(self) -> SchemaCard:
        ...

    async def validate(self, sql: str) -> ValidationResult:
        ...

    async def execute(self, sql: str) -> list[dict[str, Any]]:
        ...


# --- prompt building --------------------------------------------------------


def build_user_prompt(
    question: str,
    card: SchemaCard,
    *,
    examples: list[tuple[str, str]] | None = None,
    prior_sql: str | None = None,
    observation: str | None = None,
) -> str:
    """Assemble the grounding context for one author attempt.

    On a repair iteration ``prior_sql`` + ``observation`` (the DB error or the
    empty-result note) are appended so the model can see what went wrong.
    """
    parts = ["Schema card:", card.render(), ""]
    for ex_q, ex_sql in examples or []:
        parts.append(f"Question: {ex_q}\nSQL: {ex_sql}\n")
    parts.append(f"Question: {question}")
    if prior_sql is not None:
        parts.append("")
        parts.append("Your previous attempt:")
        parts.append(prior_sql)
        parts.append(f"It did not work: {observation}")
        parts.append("Return a corrected single SELECT.")
    parts.append("SQL:")
    return "\n".join(parts)


class ClaudeSqlModel:
    """Production :class:`SqlModel` backed by the Anthropic SDK.

    Constructed lazily so importing this module (and the test suite) never needs
    a key or network; a missing key raises on first ``author`` and the graph
    degrades to fallback.
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


# --- real read-only data seam -----------------------------------------------

_RO_POOL: Any = None
_RO_LOCK = asyncio.Lock()
READONLY_DATABASE_URL_ENV = "READONLY_DATABASE_URL"


async def get_readonly_pool() -> Any:
    """Lazy asyncpg pool for the SELECT-only role (``READONLY_DATABASE_URL``).

    Separate from the api's main ``DATABASE_URL`` pool (``db.get_pool``): the
    agent's generated SQL must run as the least-privilege role (KTD-1), never as
    the owning role. A missing URL raises a one-line setup hint pointing at
    ``tools/setup_readonly_role.py``.
    """
    global _RO_POOL
    if _RO_POOL is not None:
        return _RO_POOL
    async with _RO_LOCK:
        if _RO_POOL is None:
            url = os.environ.get(READONLY_DATABASE_URL_ENV)
            if not url:
                raise RuntimeError(
                    f"{READONLY_DATABASE_URL_ENV} is not set. Provision the read-only "
                    "role with `python tools/setup_readonly_role.py` and set the env var "
                    "(see docs/conventions/stack.md)."
                )
            import asyncpg

            _RO_POOL = await asyncpg.create_pool(url, min_size=0, max_size=4, command_timeout=10)
    return _RO_POOL


class NlSqlData:
    """Live read-only data seam. Every method acquires a connection from the
    SELECT-only pool, so the agent can author SQL it structurally cannot misuse.
    Tests do not use this class — they inject an in-memory fake."""

    def __init__(self, *, pool_getter=get_readonly_pool) -> None:
        self._pool_getter = pool_getter

    async def schema_card(self) -> SchemaCard:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            return await build_schema_card(conn)

    async def validate(self, sql: str) -> ValidationResult:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            return await validate_sql(sql, conn=conn)

    async def execute(self, sql: str) -> list[dict[str, Any]]:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        return [dict(r) for r in rows]


# --- graph state ------------------------------------------------------------


class AgentState(TypedDict, total=False):
    question: str
    data: SqlData
    model: SqlModel
    guard: Any
    examples: list[tuple[str, str]]
    max_iterations: int

    card: SchemaCard
    iterations: int
    reconsidered_empty: bool
    candidate_sql: str | None
    validation: ValidationResult | None
    observation: str | None
    rows: list[dict[str, Any]] | None
    attempts: list[dict[str, Any]]

    fallback: bool
    fallback_message: str
    result: dict[str, Any]


# --- nodes ------------------------------------------------------------------


async def assemble_context(state: AgentState) -> dict[str, Any]:
    try:
        card = await state["data"].schema_card()
    except Exception:  # noqa: BLE001
        logger.warning("nlsql: schema-card build failed; using fallback")
        return {"fallback": True, "fallback_message": _FALLBACK_MESSAGE}
    return {"card": card, "iterations": 0, "attempts": [], "reconsidered_empty": False}


async def generate_sql(state: AgentState) -> dict[str, Any]:
    """One model call to author (or repair) SQL, gated by the budget guard."""
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
        prior_sql=state.get("candidate_sql"),
        observation=state.get("observation"),
    )
    try:
        sql = await asyncio.to_thread(state["model"].author, SYSTEM_PROMPT, user)
    except Exception:  # noqa: BLE001 — never log the key or raw payload
        if guard is not None and reservation is not None:
            await guard.release(reservation)
        logger.warning("nlsql: model call failed; using fallback")
        return {"fallback": True, "fallback_message": _LLM_ERROR_MESSAGE}

    return {"candidate_sql": (sql or "").strip(), "iterations": state["iterations"] + 1}


async def validate_node(state: AgentState) -> dict[str, Any]:
    result = await state["data"].validate(state["candidate_sql"] or "")
    attempts = state.get("attempts", [])
    attempts = attempts + [
        {
            "iteration": state["iterations"],
            "sql": state["candidate_sql"],
            "status": "valid" if result.ok else "invalid",
            "reason": result.reason,
        }
    ]
    if result.ok:
        return {"validation": result, "attempts": attempts, "observation": None}
    return {"validation": result, "attempts": attempts, "observation": result.reason}


async def execute_node(state: AgentState) -> dict[str, Any]:
    sql = (state["validation"].normalized_sql if state.get("validation") else None) or ""
    try:
        rows = await state["data"].execute(sql)
    except Exception as exc:  # noqa: BLE001 — feed the DB error back, don't crash
        logger.warning("nlsql: execution failed; will repair or fall back")
        return {"rows": None, "observation": f"the query errored: {type(exc).__name__}"}
    return {"rows": rows}


async def respond(state: AgentState) -> dict[str, Any]:
    sql = state["validation"].normalized_sql if state.get("validation") else None
    rows = state.get("rows") or []
    return {
        "result": {
            "question": state["question"],
            "sql": sql,
            "rows": rows,
            "row_count": len(rows),
            "iterations": state.get("iterations", 0),
            "fallback": False,
            "attempts": state.get("attempts", []),
            "message": "",
        }
    }


async def fallback(state: AgentState) -> dict[str, Any]:
    return {
        "result": {
            "question": state["question"],
            "sql": state.get("candidate_sql"),
            "rows": [],
            "row_count": 0,
            "iterations": state.get("iterations", 0),
            "fallback": True,
            "attempts": state.get("attempts", []),
            "message": state.get("fallback_message", _FALLBACK_MESSAGE),
        }
    }


# --- edges ------------------------------------------------------------------


def _max_iters(state: AgentState) -> int:
    return state.get("max_iterations", MAX_ITERATIONS)


def _route_after_assemble(state: AgentState) -> str:
    return "fallback" if state.get("fallback") else "generate_sql"


def _route_after_generate(state: AgentState) -> str:
    return "fallback" if state.get("fallback") else "validate"


def _route_after_validate(state: AgentState) -> str:
    if state["validation"].ok:
        return "execute"
    # Invalid SQL: repair if we still have iterations, else give up.
    return "generate_sql" if state["iterations"] < _max_iters(state) else "fallback"


def _route_after_execute(state: AgentState) -> str:
    rows = state.get("rows")
    if rows is None:
        # DB error — repair if budget of iterations remains, else fall back.
        return "generate_sql" if state["iterations"] < _max_iters(state) else "fallback"
    if (
        not rows
        and not is_refusal_sql(state.get("candidate_sql"))
        and not state.get("reconsidered_empty")
        and state["iterations"] < _max_iters(state)
    ):
        # Empty result: reconsider once (maybe the filter value was wrong), then
        # accept the empty answer rather than looping forever. The refusal
        # contract is *deliberately* empty — don't burn a paid call second-guessing it.
        return "reconsider_empty"
    return "respond"


async def reconsider_empty(state: AgentState) -> dict[str, Any]:
    """Mark the one allowed empty-result reconsideration and feed it back."""
    return {
        "reconsidered_empty": True,
        "observation": (
            "the query was valid but returned zero rows — reconsider whether a "
            "filter value (entity/state/severity) was wrong or too narrow"
        ),
    }


def _build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("assemble_context", assemble_context)
    builder.add_node("generate_sql", generate_sql)
    builder.add_node("validate", validate_node)
    builder.add_node("execute", execute_node)
    builder.add_node("reconsider_empty", reconsider_empty)
    builder.add_node("respond", respond)
    builder.add_node("fallback", fallback)

    builder.add_edge(START, "assemble_context")
    builder.add_conditional_edges(
        "assemble_context",
        _route_after_assemble,
        {"generate_sql": "generate_sql", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "generate_sql",
        _route_after_generate,
        {"validate": "validate", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "validate",
        _route_after_validate,
        {"execute": "execute", "generate_sql": "generate_sql", "fallback": "fallback"},
    )
    builder.add_conditional_edges(
        "execute",
        _route_after_execute,
        {
            "respond": "respond",
            "reconsider_empty": "reconsider_empty",
            "generate_sql": "generate_sql",
            "fallback": "fallback",
        },
    )
    builder.add_edge("reconsider_empty", "generate_sql")
    builder.add_edge("respond", END)
    builder.add_edge("fallback", END)
    return builder.compile()


_GRAPH = _build_graph()


async def run_sql_query(
    question: str,
    *,
    data: SqlData,
    model: SqlModel,
    guard: Any = None,
    examples: list[tuple[str, str]] | None = None,
    max_iterations: int = MAX_ITERATIONS,
) -> dict[str, Any]:
    """Run the text-to-SQL graph. Always returns a renderable result dict:

    ``{question, sql, rows, row_count, iterations, fallback, attempts, message}``.

    Never raises on bad model output or DB errors — failures route to the
    ``fallback`` node. ``guard`` (optional) enforces a daily USD budget; omit it
    to run with no budget gating (the local CLI + unit tests do).
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
    "ClaudeSqlModel",
    "DEFAULT_MODEL",
    "MAX_ITERATIONS",
    "NlSqlData",
    "SqlData",
    "SqlModel",
    "build_user_prompt",
    "get_readonly_pool",
    "is_refusal_sql",
    "run_sql_query",
]
