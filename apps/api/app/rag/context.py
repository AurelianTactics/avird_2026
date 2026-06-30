"""RAG context assembly with provenance (plan P2, U9).

Turn retrieved narratives into a numbered, provenance-tagged context block under
a token/char budget. The numbering is the contract the citation validator (U10)
relies on: each chunk is ``[n] (incident <id>): <narrative>``, and the returned
``id_map`` resolves ``[n]`` back to the incident id — so a model citation like
``[2]`` can be checked against a real retrieved incident, and a fabricated ``[9]``
caught.

Chunks are deduped by incident id (resubmissions of one incident collapse to a
single chunk), kept in relevance order, and truncated per-chunk and in total so
the window can't blow past the budget. When the budget is hit, the
lowest-relevance chunks are dropped and the ``id_map`` contains only what was
kept — the model can't cite a chunk that isn't in the block.
"""

from __future__ import annotations

from dataclasses import dataclass

from .store import RetrievedChunk

DEFAULT_MAX_CHARS = 4000
DEFAULT_PER_CHUNK_CHARS = 600


@dataclass(frozen=True)
class ContextBlock:
    """The assembled context plus the ``[n] -> incident_id`` resolution map."""

    text: str
    id_map: dict[int, str]
    chunks: list[RetrievedChunk]


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _format_chunk(n: int, incident_id: str, narrative: str) -> str:
    return f"[{n}] (incident {incident_id}): {narrative}"


def build_context(
    retrieved: list[RetrievedChunk],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    per_chunk_chars: int = DEFAULT_PER_CHUNK_CHARS,
) -> ContextBlock:
    """Assemble retrieved chunks into a numbered context block.

    Dedupes by incident id, preserves relevance order, truncates each narrative
    to ``per_chunk_chars`` and the whole block to ``max_chars`` (dropping the
    lowest-relevance chunks that don't fit). Numbering starts at 1 over the kept
    chunks; the ``id_map`` resolves each number to its incident id.
    """
    lines: list[str] = []
    id_map: dict[int, str] = {}
    kept: list[RetrievedChunk] = []
    seen: set[str] = set()
    used = 0
    n = 0
    for chunk in retrieved:
        if chunk.incident_id in seen:
            continue
        narrative = _truncate(chunk.narrative, per_chunk_chars)
        candidate = _format_chunk(n + 1, chunk.incident_id, narrative)
        added = len(candidate) + (1 if lines else 0)  # +1 for the joining newline
        if used + added > max_chars and kept:
            # Budget hit and we already have at least one chunk — stop here so the
            # block never exceeds max_chars. Lower-relevance chunks are dropped.
            break
        n += 1
        seen.add(chunk.incident_id)
        id_map[n] = chunk.incident_id
        kept.append(chunk)
        lines.append(candidate)
        used += added
    return ContextBlock(text="\n".join(lines), id_map=id_map, chunks=kept)


__all__ = ["ContextBlock", "DEFAULT_MAX_CHARS", "DEFAULT_PER_CHUNK_CHARS", "build_context"]
