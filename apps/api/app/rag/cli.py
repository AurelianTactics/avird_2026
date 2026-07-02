"""Local-first CLI for the narrative-RAG agent (plan P2, U10).

Ask a question, watch retrieval pick narratives, see the cited answer, the
resolved incident ids, and (with ``--judge``) the faithfulness verdict.

    python -m app.rag.cli --dataset-id narratives_dedup_to_2026_03_16 "pedestrian at night"
    python -m app.rag.cli --pgvector --judge "rear-end collisions"

By default it builds the **in-memory** store from the embedding cache + raw CSVs
(the zero-setup path); ``--pgvector`` uses the ``narrative_embeddings`` table
instead. The query embedding needs ``HF_TOKEN``; the answer/judge need
``ANTHROPIC_API_KEY``. Tests inject fakes and need none of these.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from .agent import (
    BgeEmbeddingModel,
    ClaudeJudgeModel,
    ClaudeRagModel,
    EmbeddingModel,
    JudgeModel,
    RagModel,
    run_rag_query,
)
from .store import InMemoryStore, PgVectorStore, Store


def build_default_store(*, dataset_id: str, use_pgvector: bool) -> Store:
    if use_pgvector:
        # The app pool (DATABASE_URL), matching rag/routes.py: the P1 read-only
        # role was deliberately never granted narrative_embeddings — it exists
        # for model-authored SQL, and this retrieval query is fixed, trusted code.
        from ..db import get_pool

        return PgVectorStore(get_pool)
    from .ingest import build_corpus_with_vectors

    ids, narratives, matrix, report = build_corpus_with_vectors(dataset_id=dataset_id)
    print(f"[store] in-memory: {report}", file=sys.stderr)
    return InMemoryStore(ids, narratives, matrix)


def _print_result(result: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"question: {result['question']}")
    print("=" * 60)
    if result["fallback"]:
        print(f"FALLBACK: {result['message']}")
        print(f"  most relevant incidents: {result['retrieved_ids']}")
        return
    if result["refused"]:
        print("REFUSED: not supported by the retrieved narratives.")
    else:
        print(result["answer"])
    print("-" * 60)
    print(f"cited incidents:  {result['cited_incident_ids']}")
    print(f"retrieved:        {result['retrieved_ids']}")
    print(f"faithful:         {result['supported']}")
    print(f"iterations:       {result['iterations']}")


async def run_cli(
    question: str,
    *,
    store: Store,
    embedder: EmbeddingModel,
    model: RagModel,
    judge: JudgeModel | None,
    k: int,
) -> int:
    result = await run_rag_query(
        question, store=store, embedder=embedder, model=model, judge=judge, k=k
    )
    _print_result(result)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    store: Store | None = None,
    embedder: EmbeddingModel | None = None,
    model: RagModel | None = None,
    judge: JudgeModel | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", help="The natural-language question.")
    parser.add_argument("--dataset-id", default=None, help="Embedding cache dataset id.")
    parser.add_argument("--pgvector", action="store_true", help="Use the pgvector store.")
    parser.add_argument("--judge", action="store_true", help="Run the faithfulness judge.")
    parser.add_argument("-k", type=int, default=5, help="Top-k narratives to retrieve.")
    args = parser.parse_args(argv)

    if store is None:
        if not args.pgvector and not args.dataset_id:
            print("[rag.cli] --dataset-id is required for the in-memory store.", file=sys.stderr)
            return 2
        store = build_default_store(dataset_id=args.dataset_id, use_pgvector=args.pgvector)
    embedder = embedder if embedder is not None else BgeEmbeddingModel()
    model = model if model is not None else ClaudeRagModel()
    if judge is None and args.judge:
        judge = ClaudeJudgeModel()

    try:
        return asyncio.run(
            run_cli(
                args.question, store=store, embedder=embedder, model=model, judge=judge, k=args.k
            )
        )
    except RuntimeError as exc:
        print(f"[rag.cli] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
