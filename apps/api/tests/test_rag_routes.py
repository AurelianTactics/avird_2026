"""Tests for the narrative-RAG routes (P2 web delivery).

Route tests override the store, embedder, models, and budget guard with fakes
(no key, no HF, no Postgres), mirroring test_nlsql_routes.py. The contract: the
status route degrades gracefully, and the ask route never 500s on a bad question.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.rag.budget import InMemoryBudgetGuard, get_rag_budget_guard
from app.rag.routes import get_rag_embedder, get_rag_judge, get_rag_model, get_rag_store
from app.rag.store import RetrievedChunk


class FakeStore:
    def __init__(self, n=3, *, raises=False):
        self._n = n
        self._raises = raises

    async def retrieve(self, query_embedding, k, *, diversify=False):
        if self._raises:
            raise RuntimeError("store down")
        return [
            RetrievedChunk(f"inc-{i}", f"narrative {i}", 0.1 * i) for i in range(1, self._n + 1)
        ]

    async def count(self) -> int:
        if self._raises:
            raise RuntimeError("store down")
        return self._n


class FakeEmbedder:
    def embed(self, text):
        return [0.1, 0.2, 0.3]


class FakeModel:
    def __init__(self, *, answer="A pedestrian was involved [1]."):
        self._answer = answer

    def answer(self, system, user):
        return self._answer


def _override(*, store=None, model=None, judge=None, guard=None):
    app.dependency_overrides[get_rag_store] = lambda: store or FakeStore()
    app.dependency_overrides[get_rag_embedder] = FakeEmbedder
    app.dependency_overrides[get_rag_model] = lambda: model or FakeModel()
    app.dependency_overrides[get_rag_judge] = lambda: judge  # None = citation gate only
    app.dependency_overrides[get_rag_budget_guard] = lambda: guard or InMemoryBudgetGuard()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


client = TestClient(app)


# --- GET /rag/status ----------------------------------------------------------


def test_status_reports_corpus_size():
    _override(store=FakeStore(n=42))
    r = client.get("/rag/status")
    assert r.status_code == 200
    assert r.json() == {"available": True, "corpus_size": 42}


def test_status_degrades_when_store_unreachable():
    _override(store=FakeStore(raises=True))
    r = client.get("/rag/status")
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_status_empty_corpus_is_unavailable():
    # An ingested-but-empty table can't answer anything — surface that honestly.
    _override(store=FakeStore(n=0))
    r = client.get("/rag/status")
    assert r.status_code == 200
    assert r.json() == {"available": False, "corpus_size": 0}


# --- POST /rag/ask --------------------------------------------------------------


def test_ask_happy_path_returns_cited_answer_and_chunks():
    _override()
    r = client.post("/rag/ask", json={"question": "what happened to pedestrians?"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is False
    assert body["cited_incident_ids"] == ["inc-1"]
    # The page renders the retrieved narratives — full chunk detail is present.
    assert body["retrieved"][0] == {
        "incident_id": "inc-1",
        "narrative": "narrative 1",
        "distance": pytest.approx(0.1),
    }


def test_ask_never_500s_when_store_down():
    _override(store=FakeStore(raises=True))
    r = client.post("/rag/ask", json={"question": "anything"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    assert body["message"]


def test_ask_over_length_is_rejected():
    _override()
    r = client.post("/rag/ask", json={"question": "x" * 501})
    assert r.status_code == 422


def test_ask_budget_tripped_degrades_to_retrieval_only():
    _override(guard=InMemoryBudgetGuard(daily_limit_usd=0.0))
    r = client.post("/rag/ask", json={"question": "what happened?"})
    assert r.status_code == 200
    body = r.json()
    assert body["fallback"] is True
    # Retrieval-only degrade: the relevant incidents still surface.
    assert body["retrieved_ids"] == ["inc-1", "inc-2", "inc-3"]


# --- store selection (RAG_STORE env, the resolved KTD-3 open question) ---------


def test_store_default_is_pgvector(monkeypatch):
    from app.rag import routes as rag_routes
    from app.rag.store import PgVectorStore

    monkeypatch.delenv("RAG_STORE", raising=False)
    assert isinstance(rag_routes.get_rag_store(), PgVectorStore)


def test_store_memory_env_selects_in_memory(monkeypatch):
    import numpy as np

    from app.rag import routes as rag_routes
    from app.rag.store import InMemoryStore

    monkeypatch.setenv("RAG_STORE", "memory")
    fake = InMemoryStore(["a"], ["n"], np.ones((1, 3), dtype=np.float32))
    monkeypatch.setattr(rag_routes, "_build_memory_store", lambda: fake)
    assert rag_routes.get_rag_store() is fake


def test_store_memory_build_failure_degrades_to_pgvector(monkeypatch):
    from app.rag import routes as rag_routes
    from app.rag.store import PgVectorStore

    monkeypatch.setenv("RAG_STORE", "memory")

    def boom():
        raise RuntimeError("no CSVs / no cache on this machine")

    monkeypatch.setattr(rag_routes, "_build_memory_store", boom)
    # Degrades to the pgvector path (whose failures the routes already handle).
    assert isinstance(rag_routes.get_rag_store(), PgVectorStore)
