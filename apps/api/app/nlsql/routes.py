"""Text-to-SQL routes (P1 local web delivery).

Two routes exposing the open-ended text-to-SQL agent to the local web page. This
is the plan's "Phase-1 live-exposure" unit, wired for local-first: it runs the
agent as the read-only role, gated by the per-phase budget guard.

- ``GET  /nlsql/schema`` — the column data-dictionary the page shows next to the
  text box (name, type, raw-vs-clean, value samples). Built from the live DB via
  the U2 schema card, so it can't drift from the real table.
- ``POST /nlsql/query`` — author + validate + execute + repair, returning the SQL,
  the rows, and the repair trace. Never 500s on a bad query: agent failures come
  back as ``fallback=true`` (mirrors ``derived/query``).

Every collaborator is an injected FastAPI dependency (data seam, model, budget
guard) so tests run with fakes — no key, no Postgres.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .agent import ClaudeSqlModel, NlSqlData, SqlData, SqlModel, run_sql_query
from .budget import BudgetGuard, get_nlsql_budget_guard

router = APIRouter(prefix="/nlsql")

# Same input bound as the NL-filter surface — cap the body before any paid call.
MAX_QUESTION_CHARS = 500


class QueryRequest(BaseModel):
    question: str = Field(default="", max_length=MAX_QUESTION_CHARS)


def get_nlsql_data() -> SqlData:
    """FastAPI dependency for the read-only data seam. Tests override with a fake."""
    return NlSqlData()


def get_sql_model() -> SqlModel:
    """FastAPI dependency for the model client. Tests override with a fake."""
    return ClaudeSqlModel()


@router.get("/schema")
async def schema(data: SqlData = Depends(get_nlsql_data)) -> dict[str, Any]:
    """The column dictionary for the page. Degrades to an ``available=false``
    payload (never 500s) when the read-only DB is unreachable."""
    try:
        card = await data.schema_card()
    except Exception:  # noqa: BLE001 — page still renders with a notice
        return {"available": False, "table": None, "columns": [], "value_samples": {}}
    return {
        "available": True,
        "table": card.table,
        "columns": [
            {"name": c.name, "type": c.data_type, "raw": c.is_raw, "identifier": c.identifier}
            for c in card.columns
        ],
        "value_samples": card.value_samples,
    }


@router.post("/query")
async def query(
    body: QueryRequest,
    data: SqlData = Depends(get_nlsql_data),
    model: SqlModel = Depends(get_sql_model),
    guard: BudgetGuard = Depends(get_nlsql_budget_guard),
) -> dict[str, Any]:
    """Run the text-to-SQL agent. Always returns a renderable result dict
    ``{question, sql, rows, row_count, iterations, fallback, attempts, message}``;
    never 500s on a bad query (agent failures surface as ``fallback=true``)."""
    return await run_sql_query(body.question, data=data, model=model, guard=guard)
