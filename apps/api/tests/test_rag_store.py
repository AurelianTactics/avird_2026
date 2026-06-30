"""Tests for the RAG embedding store + ingest hash-join (plan P2, U8).

The in-memory path runs on synthetic numpy matrices (no parquet, no network);
the pgvector path uses a fake pool. The ingest tests pin the hash-join contract:
nothing is silently dropped, and the local hash matches the cache's hash exactly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

from app.rag import ingest
from app.rag.store import InMemoryStore, PgVectorStore, RetrievedChunk, cosine_distances

# --- cosine ----------------------------------------------------------------


class TestCosine:
    def test_identical_vector_is_distance_zero(self):
        m = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
        d = cosine_distances(m, np.array([1.0, 0.0], dtype=np.float32))
        assert d[0] == pytest.approx(0.0, abs=1e-6)
        assert d[1] == pytest.approx(1.0, abs=1e-6)

    def test_opposite_vector_is_distance_two(self):
        m = np.array([[-1.0, 0.0]], dtype=np.float32)
        d = cosine_distances(m, np.array([1.0, 0.0], dtype=np.float32))
        assert d[0] == pytest.approx(2.0, abs=1e-6)

    def test_empty_matrix(self):
        d = cosine_distances(np.zeros((0, 4), dtype=np.float32), np.ones(4, dtype=np.float32))
        assert d.shape == (0,)


# --- InMemoryStore ----------------------------------------------------------


def _corpus(n=8, dim=6, seed=0):
    rng = np.random.default_rng(seed)
    matrix = rng.normal(size=(n, dim)).astype(np.float32)
    ids = [f"inc-{i}" for i in range(n)]
    narratives = [f"narrative {i}" for i in range(n)]
    return ids, narratives, matrix


class TestInMemoryStore:
    async def test_returns_k_nearest_in_distance_order(self):
        ids, narr, matrix = _corpus()
        store = InMemoryStore(ids, narr, matrix)
        # Query = exactly row 3 → row 3 is the nearest (distance ~0).
        out = await store.retrieve(matrix[3], k=3)
        assert len(out) == 3
        assert out[0].incident_id == "inc-3"
        assert out[0].distance == pytest.approx(0.0, abs=1e-6)
        # Distances are non-decreasing.
        assert [c.distance for c in out] == sorted(c.distance for c in out)

    async def test_k_larger_than_corpus_is_clamped(self):
        ids, narr, matrix = _corpus(n=4)
        store = InMemoryStore(ids, narr, matrix)
        out = await store.retrieve(matrix[0], k=99)
        assert len(out) == 4

    async def test_k_non_positive_returns_empty(self):
        ids, narr, matrix = _corpus(n=4)
        store = InMemoryStore(ids, narr, matrix)
        assert await store.retrieve(matrix[0], k=0) == []

    async def test_returns_retrieved_chunks_with_provenance(self):
        ids, narr, matrix = _corpus(n=3)
        store = InMemoryStore(ids, narr, matrix)
        out = await store.retrieve(matrix[1], k=1)
        assert isinstance(out[0], RetrievedChunk)
        assert out[0].narrative == "narrative 1"

    async def test_mmr_diversify_avoids_near_duplicates(self):
        # Rows 0 and 1 are near-identical; row 2 is also relevant but distinct.
        matrix = np.array([[1.0, 0.0, 0.0], [1.0, 0.0, 0.001], [0.9, 0.4, 0.0]], dtype=np.float32)
        store = InMemoryStore(["a", "b", "c"], ["dup1", "dup2", "distinct"], matrix)
        query = np.array([1.0, 0.1, 0.0], dtype=np.float32)
        plain = await store.retrieve(query, k=2)
        diverse = await store.retrieve(query, k=2, diversify=True)
        # Plain top-2 are the two near-duplicates; MMR swaps one for the distinct row.
        assert {c.incident_id for c in plain} == {"a", "b"}
        assert "c" in {c.incident_id for c in diverse}

    def test_misaligned_inputs_raise(self):
        with pytest.raises(ValueError):
            InMemoryStore(["a"], ["x", "y"], np.zeros((1, 3), dtype=np.float32))


# --- PgVectorStore ----------------------------------------------------------


class FakePool:
    def __init__(self, rows):
        self._rows = rows
        self.queries: list[tuple] = []

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return _Conn(pool)

            async def __aexit__(self, *a):
                return False

        return _Ctx()


class _Conn:
    def __init__(self, pool):
        self._pool = pool

    async def fetch(self, query, *args):
        self._pool.queries.append((query, args))
        return list(self._pool._rows)


class TestPgVectorStore:
    async def test_maps_rows_to_chunks(self):
        rows = [
            {"incident_id": "inc-1", "narrative": "n1", "distance": 0.1},
            {"incident_id": "inc-2", "narrative": "n2", "distance": 0.3},
        ]
        pool = FakePool(rows)
        store = PgVectorStore(lambda: _async(pool))
        out = await store.retrieve([0.1, 0.2, 0.3], k=2)
        assert [c.incident_id for c in out] == ["inc-1", "inc-2"]
        # The query was sent as a ::vector literal with a LIMIT param.
        sent_query, sent_args = pool.queries[0]
        assert "::vector" in sent_query and "LIMIT" in sent_query
        assert sent_args[0].startswith("[") and sent_args[1] == 2

    async def test_non_positive_k_short_circuits(self):
        pool = FakePool([])
        store = PgVectorStore(lambda: _async(pool))
        assert await store.retrieve([0.0], k=0) == []
        assert pool.queries == []


async def _async(value):
    return value


# --- ingest hash-join -------------------------------------------------------


class TestJoinVectors:
    def test_matches_by_hash_and_carries_id_and_narrative(self):
        rows = [{"incident_id": "inc-1", "narrative": "a crash at night"}]
        cache = {ingest._text_hash("a crash at night"): [0.1, 0.2]}
        matched, report = ingest.join_vectors(rows, cache)
        assert report["n_matched"] == 1
        m = matched[0]
        assert m["incident_id"] == "inc-1" and m["narrative"] == "a crash at night"
        assert m["vector"] == [0.1, 0.2]

    def test_unmatched_is_reported_not_dropped(self):
        rows = [
            {"incident_id": "inc-1", "narrative": "present"},
            {"incident_id": "inc-2", "narrative": "missing from cache"},
        ]
        cache = {ingest._text_hash("present"): [1.0]}
        matched, report = ingest.join_vectors(rows, cache)
        assert report["n_matched"] == 1
        assert report["n_unmatched"] == 1
        assert "inc-2" in report["unmatched_sample"]

    def test_empty_narrative_is_skipped_and_counted(self):
        rows = [{"incident_id": "inc-1", "narrative": "   "}]
        matched, report = ingest.join_vectors(rows, {})
        assert matched == []
        assert report["n_empty"] == 1

    def test_every_matched_row_has_non_null_id_and_narrative(self):
        rows = [{"incident_id": "", "narrative": "no id but has text"}]
        cache = {ingest._text_hash("no id but has text"): [0.0]}
        matched, _ = ingest.join_vectors(rows, cache)
        assert matched[0]["incident_id"] == "(no id)"
        assert matched[0]["narrative"]

    def test_local_hash_matches_eda_cache_hash(self):
        # The whole join hinges on this: our hash must equal the one the cache
        # was written with, or every row would be reported unmatched.
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "eda"))
        from eda_utils_embed import _text_hash as eda_hash

        text = "  A pedestrian crossed mid-block.  "
        assert ingest._text_hash(text) == eda_hash(text)
