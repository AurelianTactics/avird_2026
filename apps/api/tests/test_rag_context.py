"""Tests for RAG context assembly (plan P2, U9).

The numbered block + id_map is the provenance contract the citation validator
depends on, so the tests pin: numbering, dedup, budget-driven dropping, and
per-chunk truncation.
"""

from __future__ import annotations

from app.rag.context import build_context
from app.rag.store import RetrievedChunk


def _chunks(n, *, narrative="a crash narrative", start=0):
    return [
        RetrievedChunk(incident_id=f"inc-{i}", narrative=f"{narrative} {i}", distance=0.1 * i)
        for i in range(start, start + n)
    ]


def test_numbers_chunks_and_maps_ids():
    block = build_context(_chunks(5))
    assert block.id_map == {1: "inc-0", 2: "inc-1", 3: "inc-2", 4: "inc-3", 5: "inc-4"}
    assert "[1] (incident inc-0):" in block.text
    assert "[5] (incident inc-4):" in block.text
    assert len(block.chunks) == 5


def test_duplicate_incident_ids_collapse():
    dup = RetrievedChunk(incident_id="inc-0", narrative="same incident again", distance=0.5)
    block = build_context(_chunks(2) + [dup])
    assert len(block.chunks) == 2
    assert list(block.id_map.values()) == ["inc-0", "inc-1"]


def test_budget_drops_lowest_relevance_and_id_map_only_keeps():
    # A tiny budget keeps only the first chunk; later (lower-relevance) ones drop.
    block = build_context(_chunks(5), max_chars=60, per_chunk_chars=600)
    assert len(block.chunks) >= 1
    assert len(block.chunks) < 5
    # id_map keys are contiguous from 1 and only cover kept chunks.
    assert set(block.id_map) == set(range(1, len(block.chunks) + 1))
    assert len(block.text) <= 60 or len(block.chunks) == 1


def test_per_chunk_truncation_adds_ellipsis():
    long = "x" * 1000
    block = build_context([RetrievedChunk("inc-0", long, 0.1)], per_chunk_chars=50)
    assert "…" in block.text
    # The chunk body is capped near per_chunk_chars (plus the "[1] (incident ...)" prefix).
    assert len(block.text) < 120


def test_empty_input_yields_empty_block():
    block = build_context([])
    assert block.text == ""
    assert block.id_map == {}


def test_id_map_resolves_back_to_incident_ids():
    # The U10 contract: a citation [n] must resolve to a retrieved incident.
    block = build_context(_chunks(3))
    for n, incident_id in block.id_map.items():
        assert f"[{n}] (incident {incident_id})" in block.text
