"""Narrative embedding store: pgvector + in-memory fallback (plan P2, U8).

The retrieval backbone. Two backends behind one ``retrieve`` signature (KTD-3):

- :class:`PgVectorStore` — the "real" path: ``ORDER BY embedding <=> $1 LIMIT k``
  cosine search over the ``narrative_embeddings`` table (``db/pgvector_setup.sql``).
- :class:`InMemoryStore` — the zero-setup fallback: a vendored numpy cosine search
  over an in-memory matrix, used when pgvector isn't available locally (stock
  Windows PG 17 doesn't bundle the extension — see the plan's Open Questions).

Cosine search is vendored (~numpy only) rather than pulled from ``eda`` so the
api doesn't take a scikit-learn dependency. The query embedding is computed
*outside* the store (by the RAG agent's embedding adapter) and passed in, so the
store never needs ``huggingface_hub``.

numpy is imported at module top: since the P2 live-exposure routes (``rag/routes.py``)
mount this store in the FastAPI app, numpy is a declared api dependency
(pyproject + requirements.txt). The heavy ingest deps (pandas/pyarrow) remain
offline-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

EMBEDDING_DIM = 768  # BAAI/bge-base-en-v1.5
TABLE = "narrative_embeddings"


@dataclass(frozen=True)
class RetrievedChunk:
    """One retrieved narrative with its provenance and cosine distance."""

    incident_id: str
    narrative: str
    distance: float


class Store(Protocol):
    """The retrieval seam both backends satisfy."""

    async def retrieve(
        self, query_embedding: Any, k: int, *, diversify: bool = False
    ) -> list[RetrievedChunk]: ...

    async def count(self) -> int: ...


# --- vendored cosine (numpy only) -------------------------------------------


def _unit(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalize, guarding against zero-norm rows."""
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return vectors / norms


def cosine_distances(matrix: np.ndarray, query: np.ndarray) -> np.ndarray:
    """Cosine distance (1 - similarity) from each row of ``matrix`` to ``query``."""
    if matrix.size == 0:
        return np.zeros((0,), dtype=np.float32)
    sims = _unit(matrix) @ _unit(query.reshape(1, -1)).reshape(-1)
    return 1.0 - sims


def _mmr_order(matrix: np.ndarray, query: np.ndarray, k: int, lam: float) -> list[int]:
    """Maximal-marginal-relevance ordering: balance query relevance against
    redundancy so near-duplicate narratives (resubmissions of one incident) don't
    crowd out the top results."""
    units = _unit(matrix)
    rel = units @ _unit(query.reshape(1, -1)).reshape(-1)  # similarity to query
    selected: list[int] = []
    candidates = list(range(matrix.shape[0]))
    while candidates and len(selected) < k:
        if not selected:
            best = max(candidates, key=lambda i: rel[i])
        else:
            sel = units[selected]
            best, best_score = candidates[0], float("-inf")
            for i in candidates:
                redundancy = float(np.max(sel @ units[i]))
                score = lam * float(rel[i]) - (1.0 - lam) * redundancy
                if score > best_score:
                    best, best_score = i, score
        selected.append(best)
        candidates.remove(best)
    return selected


class InMemoryStore:
    """In-memory cosine retrieval over a fixed corpus matrix."""

    def __init__(self, ids: list[str], narratives: list[str], matrix: np.ndarray):
        if not (len(ids) == len(narratives) == matrix.shape[0]):
            raise ValueError("ids, narratives, and matrix rows must align")
        self._ids = ids
        self._narratives = narratives
        self._matrix = np.asarray(matrix, dtype=np.float32)

    def __len__(self) -> int:
        return len(self._ids)

    async def count(self) -> int:
        return len(self._ids)

    async def retrieve(
        self, query_embedding: Any, k: int, *, diversify: bool = False, mmr_lambda: float = 0.5
    ) -> list[RetrievedChunk]:
        n = len(self._ids)
        if n == 0 or k <= 0:
            return []
        k = min(k, n)  # clamp k to the corpus size
        query = np.asarray(query_embedding, dtype=np.float32)
        distances = cosine_distances(self._matrix, query)
        if diversify:
            order = _mmr_order(self._matrix, query, k, mmr_lambda)
        else:
            order = list(np.argsort(distances, kind="stable")[:k])
        return [
            RetrievedChunk(
                incident_id=self._ids[i],
                narrative=self._narratives[i],
                distance=float(distances[i]),
            )
            for i in order
        ]


class PgVectorStore:
    """pgvector-backed cosine retrieval over ``narrative_embeddings``."""

    def __init__(self, pool_getter):
        self._pool_getter = pool_getter

    @staticmethod
    def _vector_literal(query_embedding: Any) -> str:
        return "[" + ",".join(repr(float(x)) for x in query_embedding) + "]"

    async def count(self) -> int:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            return int(await conn.fetchval(f"SELECT count(*) FROM {TABLE}"))

    async def retrieve(
        self, query_embedding: Any, k: int, *, diversify: bool = False
    ) -> list[RetrievedChunk]:
        if k <= 0:
            return []
        # ``diversify`` (MMR) is an in-memory refinement; for pgvector we
        # over-fetch and could re-rank, but keep the SQL path a plain ANN scan.
        vec = self._vector_literal(query_embedding)
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT incident_id, narrative, embedding <=> $1::vector AS distance "
                f"FROM {TABLE} ORDER BY embedding <=> $1::vector LIMIT $2",
                vec,
                k,
            )
        return [
            RetrievedChunk(
                incident_id=r["incident_id"],
                narrative=r["narrative"],
                distance=float(r["distance"]),
            )
            for r in rows
        ]


__all__ = [
    "EMBEDDING_DIM",
    "InMemoryStore",
    "PgVectorStore",
    "RetrievedChunk",
    "Store",
    "cosine_distances",
]
