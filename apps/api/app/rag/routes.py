"""Narrative-RAG routes (P2 local web delivery).

Two routes exposing the grounded-RAG agent to the local web page — the plan's
"Phase-2 live-exposure" unit, mirroring ``nlsql/routes.py``:

- ``GET  /rag/status`` — whether the pgvector store is reachable and how many
  narratives are indexed (the page shows this next to the ask box). Degrades to
  ``available=false``, never 500s.
- ``POST /rag/ask`` — embed the question, retrieve narratives, generate a cited
  answer, run the citation gate + faithfulness judge, returning the answer, the
  resolved citations, and the retrieved narratives. Never 500s on a bad question:
  agent failures come back as ``fallback=true`` (retrieval-only degrade).

The store queries the **app pool**, not the P1 read-only role: the retrieval SQL
is fixed, trusted code — the read-only role exists for *model-authored* SQL, and
was deliberately never granted ``narrative_embeddings``.

**Store selection (the resolved KTD-3 open question):** ``CREATE EXTENSION
vector`` fails on the local Windows PG 17 (no bundled extension), so
``RAG_STORE=memory`` selects the in-memory corpus (embedding cache + raw CSVs,
built lazily once per process) as the *local* default; the pgvector path is the
production default and is validated against Railway PG 16 before live exposure.

Every collaborator is an injected FastAPI dependency (store, embedder, answer
model, judge, budget guard) so tests run with fakes — no key, no HF, no Postgres.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..db import get_pool
from .agent import (
    BgeEmbeddingModel,
    ClaudeJudgeModel,
    ClaudeRagModel,
    EmbeddingModel,
    RagModel,
    run_rag_query,
)
from .budget import BudgetGuard, get_rag_budget_guard
from .store import InMemoryStore, PgVectorStore, Store

logger = logging.getLogger(__name__)

DEFAULT_DATASET_ID = "narratives_dedup_to_2026_03_16"

router = APIRouter(prefix="/rag")

# Same input bound as the other NL surfaces — cap the body before any paid call.
MAX_QUESTION_CHARS = 500


class AskRequest(BaseModel):
    question: str = Field(default="", max_length=MAX_QUESTION_CHARS)


_memory_store: InMemoryStore | None = None


def _build_memory_store() -> InMemoryStore:
    """Lazy per-process in-memory corpus (embedding cache joined to the deduped
    CSV rows — the U8 ingest path). Local-dev only: needs the eda deps + raw CSVs,
    which the deployed api image doesn't carry."""
    global _memory_store
    if _memory_store is None:
        from .ingest import build_corpus_with_vectors

        dataset_id = os.environ.get("RAG_DATASET_ID", DEFAULT_DATASET_ID)
        ids, narratives, matrix, report = build_corpus_with_vectors(dataset_id=dataset_id)
        logger.info("rag: in-memory store built (%s)", report)
        _memory_store = InMemoryStore(ids, narratives, matrix)
    return _memory_store


def get_rag_store() -> Store:
    """FastAPI dependency for the retrieval store. Tests override with a fake.

    ``RAG_STORE=memory`` (local default — see module docstring) selects the
    in-memory corpus; anything else selects pgvector over the app pool. A failed
    in-memory build degrades to the pgvector path so the routes' own exception
    handling (``available=false`` / ``fallback=true``) still applies."""
    if os.environ.get("RAG_STORE", "").strip().lower() in ("memory", "in-memory", "inmemory"):
        try:
            return _build_memory_store()
        except Exception:  # noqa: BLE001 — degrade, never 500 at dependency time
            logger.warning("rag: in-memory store build failed; using pgvector path")
    return PgVectorStore(get_pool)


def get_rag_embedder() -> EmbeddingModel:
    """FastAPI dependency for the query embedder (HF, lazy). Tests override."""
    return BgeEmbeddingModel()


def get_rag_model() -> RagModel:
    """FastAPI dependency for the answer model. Tests override with a fake."""
    return ClaudeRagModel()


def get_rag_judge() -> Any:
    """FastAPI dependency for the faithfulness judge (``None`` disables it and
    leaves only the structural citation gate). ``RAG_JUDGE_ENABLED=0`` turns it
    off — the judge is the pricier sonnet call, so this halves per-question cost."""
    if os.environ.get("RAG_JUDGE_ENABLED", "1").strip().lower() in ("0", "false"):
        return None
    return ClaudeJudgeModel()


@router.get("/status")
async def status(store: Store = Depends(get_rag_store)) -> dict[str, Any]:
    """Store reachability + corpus size for the page. Degrades to
    ``available=false`` (never 500s) when pgvector/the table is missing."""
    try:
        n = await store.count()
    except Exception:  # noqa: BLE001 — page still renders with a notice
        return {"available": False, "corpus_size": 0}
    return {"available": n > 0, "corpus_size": n}


@router.post("/ask")
async def ask(
    body: AskRequest,
    store: Store = Depends(get_rag_store),
    embedder: EmbeddingModel = Depends(get_rag_embedder),
    model: RagModel = Depends(get_rag_model),
    judge: Any = Depends(get_rag_judge),
    guard: BudgetGuard = Depends(get_rag_budget_guard),
) -> dict[str, Any]:
    """Run the RAG agent. Always returns a renderable result dict
    ``{question, answer, cited_incident_ids, retrieved_ids, retrieved, supported,
    refused, iterations, fallback, message}``; never 500s on a bad question."""
    return await run_rag_query(
        body.question, store=store, embedder=embedder, model=model, judge=judge, guard=guard
    )
