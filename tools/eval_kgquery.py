"""Golden eval for the NL→Cypher agent — answer-set equivalence + F1 (P3, U16).

The honest measure of a generated Cypher query is **what it returns**, not how
it reads. This harness runs the agent's candidate and a hand-written
``gold_cypher`` against the live graph (both in read-access mode) and compares
their **result sets** (order-insensitive, floats rounded): exact-set accuracy,
answer-set F1 partial credit, refusal precision/recall on the
deliberately-unanswerable rows, and mean repair iterations.

It mirrors ``tools/eval_nlsql.py`` / ``ontology/evaluate.py``: held-out is
final-numbers-only (refused without ``--heldout``), and the summary is a
deterministic JSON + markdown table committed under ``tools/results/``.

The scoring core (normalization, equality, F1, refusal detection, aggregation)
is pure and unit-tested with fakes; ``main`` wires the real agent + a gold
executor against the Railway graph and needs ``NEO4J_*`` + a key.

Golden row shape (``golden/kgquery/{dev,heldout}.jsonl``)::

    {"question": "...", "gold_cypher": "MATCH ... RETURN ...", "kind": "aggregation"}
    {"question": "...", "gold_cypher": "RETURN NULL LIMIT 0", "unanswerable": true}
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Split hygiene, jsonl loading, result-set normalization, and the summary
# writer are metric-agnostic infra shared by every eval harness — import from
# the P1 harness (the precedent eval_rag.py set) instead of re-copying.
from eval_nlsql import (
    _mean,
    _row_tuple,
    canonical,
    exact_match,
    golden_split_path,
    load_jsonl,
    write_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO_ROOT / "golden" / "kgquery"

__all__ = ["canonical", "exact_match", "golden_split_path", "load_jsonl", "write_summary"]


# ---------------------------------------------------------------------------
# Scoring (pure — the P3-specific metric)
# ---------------------------------------------------------------------------
def answer_set_f1(candidate_rows, gold_rows):
    """Row-set F1 — partial credit for supersets/subsets (the plan's P3 metric)."""
    a = set(_row_tuple(r) for r in candidate_rows)
    b = set(_row_tuple(r) for r in gold_rows)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    overlap = len(a & b)
    return round(2 * overlap / (len(a) + len(b)), 4)


# The refusal contract, tolerant of whitespace/case (the validator leaves
# "RETURN NULL LIMIT 0" unchanged — it already carries a LIMIT).
_REFUSAL_CYPHER = re.compile(r"^returnnulllimit0$")


def is_refusal(candidate):
    """Did the agent refuse — fallback, or the ``RETURN NULL LIMIT 0`` contract?"""
    if candidate.get("fallback"):
        return True
    cypher = candidate.get("cypher") or ""
    return bool(_REFUSAL_CYPHER.match(re.sub(r"[\s;]+", "", cypher).lower()))


def score_case(case, candidate, gold_rows):
    """Score one golden row against the agent's candidate + the gold result set."""
    refused = is_refusal(candidate)
    if case.get("unanswerable"):
        # Correct iff the agent refused to answer the unanswerable question.
        return {
            "question": case["question"],
            "unanswerable": True,
            "refused": refused,
            "correct": refused,
            "f1": 1.0 if refused else 0.0,
            "iterations": candidate.get("iterations", 0),
        }
    # Answerable: refusing or falling back is wrong; otherwise compare results.
    correct = (not refused) and exact_match(candidate.get("rows", []), gold_rows)
    f1 = 0.0 if refused else answer_set_f1(candidate.get("rows", []), gold_rows)
    return {
        "question": case["question"],
        "unanswerable": False,
        "refused": refused,
        "correct": correct,
        "f1": f1,
        "iterations": candidate.get("iterations", 0),
    }


def aggregate(scored):
    answerable = [s for s in scored if not s["unanswerable"]]
    unanswerable = [s for s in scored if s["unanswerable"]]
    refused = [s for s in scored if s["refused"]]
    refused_correctly = [s for s in refused if s["unanswerable"]]
    return {
        "n": len(scored),
        "n_answerable": len(answerable),
        "n_unanswerable": len(unanswerable),
        "accuracy": _mean(s["correct"] for s in answerable),
        "mean_answer_set_f1": _mean(s["f1"] for s in answerable),
        "refusal_precision": round(len(refused_correctly) / len(refused), 4) if refused else 0.0,
        "refusal_recall": _mean(s["refused"] for s in unanswerable),
        "mean_iterations": _mean(s["iterations"] for s in scored),
    }


def evaluate(cases, run_agent, run_gold):
    """Score every case. ``run_agent(question)`` returns a result dict (U15
    shape); ``run_gold(cypher)`` returns the gold result rows. Both are injected
    so this is pure and testable; ``main`` supplies the graph-backed ones."""
    scored = []
    for case in cases:
        candidate = run_agent(case["question"])
        gold_rows = [] if case.get("unanswerable") else run_gold(case["gold_cypher"])
        scored.append(score_case(case, candidate, gold_rows))
    return {"metrics": aggregate(scored), "cases": scored}


# ---------------------------------------------------------------------------
# Real runner (needs the live graph via NEO4J_* + ANTHROPIC_API_KEY)
# ---------------------------------------------------------------------------
def _run_real(cases, *, max_iterations):
    import asyncio
    import os

    sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))
    from app.kgquery.agent import ClaudeCypherModel, Neo4jKgData, run_kg_query

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY not set — cannot run the agent for eval.", file=sys.stderr)
        return None
    model = ClaudeCypherModel()
    data = Neo4jKgData()

    async def _go():
        # Gold Cypher runs through the same read-mode seam as the agent's.
        async def run_gold(cypher):
            return await data.execute(cypher)

        scored = []
        for case in cases:
            candidate = await run_kg_query(
                case["question"], data=data, model=model, max_iterations=max_iterations
            )
            if not candidate.get("graph_available", True):
                print(
                    "graph unreachable — start the Railway Neo4j / TCP proxy first.",
                    file=sys.stderr,
                )
                return None
            gold_rows = [] if case.get("unanswerable") else await run_gold(case["gold_cypher"])
            scored.append(score_case(case, candidate, gold_rows))
        return {"metrics": aggregate(scored), "cases": scored}

    return asyncio.run(_go())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--heldout", action="store_true", help="Score the held-out split (final only).")
    p.add_argument("--max-iterations", type=int, default=3)
    p.add_argument("--out-name", default=None)
    args = p.parse_args(argv)

    split = "heldout" if args.heldout else "dev"
    cases = load_jsonl(golden_split_path(split, allow_heldout=args.heldout, golden_dir=GOLDEN_DIR))
    result = _run_real(cases, max_iterations=args.max_iterations)
    if result is None:
        return 2
    name = args.out_name or f"kgquery-eval-{split}"
    paths = write_summary(result["metrics"], name, inputs={"split": split, "n": len(cases)})
    m = result["metrics"]
    print(f"accuracy:            {m['accuracy']}")
    print(f"mean answer-set F1:  {m['mean_answer_set_f1']}")
    print(f"refusal precision:   {m['refusal_precision']}")
    print(f"mean iterations:     {m['mean_iterations']}")
    print(f"summary: {paths[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
