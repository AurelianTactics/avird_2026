"""Golden eval for the narrative-RAG agent (plan P2, U11).

Two metrics, matching the two validation tiers RAG cares about:

- **Citation recall / precision** — did the agent cite the incidents a human
  judged relevant (``expected_incident_ids``), and did it avoid citing irrelevant
  ones? This is the retrieval-quality signal.
- **Answer-point coverage** — deterministic keyword coverage of the
  ``answer_points`` a good answer should hit (an LLM-judge variant is possible but
  non-deterministic; keyword coverage keeps the committed number reproducible).

Plus refusal precision/recall over the deliberately-unsupported rows. Reuses the
held-out hygiene guard + summary writer from ``eval_nlsql``.

Golden row shape (``golden/rag/{dev,heldout}.jsonl``)::

    {"question": "...", "expected_incident_ids": ["..."], "answer_points": ["..."]}
    {"question": "...", "unsupported": true}

``expected_incident_ids`` is hand-labeled (run the RAG CLI, review the retrieved
incidents — see golden/rag/README.md); rows left unlabeled (``[]``) are scored on
coverage only and excluded from the citation means.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eval_nlsql import _mean, golden_split_path, load_jsonl, write_summary

REPO_ROOT = Path(__file__).resolve().parents[1]
RAG_GOLDEN_DIR = REPO_ROOT / "golden" / "rag"


# ---------------------------------------------------------------------------
# Scoring (pure)
# ---------------------------------------------------------------------------
def citation_metrics(cited_ids, expected_ids):
    """Recall + precision of cited incidents vs the expected set.

    Returns ``None`` when ``expected_ids`` is empty (row not yet hand-labeled) so
    it doesn't pollute the means.
    """
    expected = set(expected_ids or [])
    if not expected:
        return None
    cited = set(cited_ids or [])
    hit = len(cited & expected)
    recall = hit / len(expected)
    precision = hit / len(cited) if cited else 0.0
    return {"recall": round(recall, 4), "precision": round(precision, 4)}


def answer_point_coverage(answer, answer_points):
    """Fraction of ``answer_points`` whose text appears (case-insensitive) in the
    answer. ``None`` when there are no points to score."""
    points = answer_points or []
    if not points:
        return None
    text = (answer or "").lower()
    hit = sum(1 for p in points if str(p).lower() in text)
    return round(hit / len(points), 4)


def _is_refusal(candidate):
    return bool(candidate.get("refused") or candidate.get("fallback"))


def score_case(case, candidate):
    if case.get("unsupported"):
        refused = _is_refusal(candidate)
        return {
            "question": case["question"],
            "unsupported": True,
            "refused": refused,
            "correct": refused,
        }
    cm = citation_metrics(candidate.get("cited_incident_ids"), case.get("expected_incident_ids"))
    cov = answer_point_coverage(candidate.get("answer"), case.get("answer_points"))
    return {
        "question": case["question"],
        "unsupported": False,
        "refused": _is_refusal(candidate),
        "citation": cm,
        "coverage": cov,
    }


def aggregate(scored):
    answerable = [s for s in scored if not s["unsupported"]]
    unsupported = [s for s in scored if s["unsupported"]]
    labeled = [s for s in answerable if s.get("citation") is not None]
    covered = [s for s in answerable if s.get("coverage") is not None]
    refused = [s for s in scored if s["refused"]]
    refused_correctly = [s for s in refused if s["unsupported"]]
    return {
        "n": len(scored),
        "n_answerable": len(answerable),
        "n_labeled": len(labeled),
        "n_unsupported": len(unsupported),
        "mean_citation_recall": _mean(s["citation"]["recall"] for s in labeled),
        "mean_citation_precision": _mean(s["citation"]["precision"] for s in labeled),
        "mean_answer_coverage": _mean(s["coverage"] for s in covered),
        "refusal_precision": round(len(refused_correctly) / len(refused), 4) if refused else 0.0,
        "refusal_recall": _mean(s["refused"] for s in unsupported),
    }


def evaluate(cases, run_agent):
    """Score every case. ``run_agent(question)`` returns a RAG result dict (U10
    shape). Pure over the injected runner so it's unit-testable."""
    scored = [score_case(case, run_agent(case["question"])) for case in cases]
    return {"metrics": aggregate(scored), "cases": scored}


# ---------------------------------------------------------------------------
# Real runner (needs the embedding cache + ANTHROPIC_API_KEY + HF_TOKEN)
# ---------------------------------------------------------------------------
def _run_real(cases, *, dataset_id, use_pgvector, use_judge):
    import asyncio
    import os

    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    from app.rag.agent import (
        BgeEmbeddingModel,
        ClaudeJudgeModel,
        ClaudeRagModel,
        run_rag_query,
    )
    from app.rag.cli import build_default_store

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot run the RAG agent for eval.", file=sys.stderr)
        return None
    store = build_default_store(dataset_id=dataset_id, use_pgvector=use_pgvector)
    embedder = BgeEmbeddingModel()
    model = ClaudeRagModel()
    judge = ClaudeJudgeModel() if use_judge else None

    async def _go():
        scored = []
        for case in cases:
            result = await run_rag_query(
                case["question"], store=store, embedder=embedder, model=model, judge=judge
            )
            scored.append(score_case(case, result))
        return {"metrics": aggregate(scored), "cases": scored}

    return asyncio.run(_go())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--heldout", action="store_true", help="Score the held-out split (final only).")
    p.add_argument("--dataset-id", default=None, help="Embedding cache dataset id.")
    p.add_argument("--pgvector", action="store_true")
    p.add_argument("--judge", action="store_true")
    p.add_argument("--out-name", default=None)
    args = p.parse_args(argv)

    split = "heldout" if args.heldout else "dev"
    cases = load_jsonl(
        golden_split_path(split, allow_heldout=args.heldout, golden_dir=RAG_GOLDEN_DIR)
    )
    if not args.pgvector and not args.dataset_id:
        print("--dataset-id is required for the in-memory store.", file=sys.stderr)
        return 2
    result = _run_real(
        cases, dataset_id=args.dataset_id, use_pgvector=args.pgvector, use_judge=args.judge
    )
    if result is None:
        return 2
    name = args.out_name or f"rag-eval-{split}"
    paths = write_summary(result["metrics"], name, inputs={"split": split, "n": len(cases)})
    m = result["metrics"]
    print(f"citation recall:    {m['mean_citation_recall']}")
    print(f"citation precision: {m['mean_citation_precision']}")
    print(f"answer coverage:    {m['mean_answer_coverage']}")
    print(f"summary: {paths[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
