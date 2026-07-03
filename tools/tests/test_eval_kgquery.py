"""Tests for the kgquery eval harness (plan P3, U16).

The scoring core is pure: answer-set equivalence (order-insensitive, floats
rounded), answer-set F1 partial credit, refusal detection, and aggregation.
The graph-backed runner is exercised by hand against the live graph; here
``evaluate`` runs with injected fakes. Also checks the held-out hygiene guard
and summary determinism.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import eval_kgquery as e

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- held-out hygiene -------------------------------------------------------


class TestSplitHygiene:
    def test_heldout_refused_without_flag(self):
        with pytest.raises(PermissionError):
            e.golden_split_path("heldout")

    def test_heldout_allowed_with_flag(self):
        assert e.golden_split_path("heldout", allow_heldout=True).name == "heldout.jsonl"

    def test_dev_always_allowed(self):
        assert e.golden_split_path("dev").name == "dev.jsonl"

    def test_committed_golden_rows_are_well_formed(self):
        for split in ("dev", "heldout"):
            rows = e.load_jsonl(
                e.golden_split_path(split, allow_heldout=True, golden_dir=e.GOLDEN_DIR)
            )
            assert rows, f"{split} split is empty"
            for row in rows:
                assert row["question"]
                assert row["gold_cypher"]
                if row.get("unanswerable"):
                    assert row["gold_cypher"] == "RETURN NULL LIMIT 0"


# --- result-set equality + F1 -------------------------------------------------


class TestScoring:
    def test_order_insensitive_match(self):
        a = [{"company": "Waymo", "n": 3}, {"company": "Cruise", "n": 2}]
        b = [{"n": 2, "company": "Cruise"}, {"company": "Waymo", "n": 3}]
        assert e.exact_match(a, b)

    def test_alias_differences_still_match_on_values(self):
        a = [{"n": 5}]
        b = [{"incidents": 5}]
        assert e.exact_match(a, b)

    def test_float_rounding(self):
        assert e.exact_match([{"share": 0.66666648}], [{"share": 0.66666652}])

    def test_superset_scores_partial_f1_not_full(self):
        gold = [{"x": 1}, {"x": 2}]
        candidate = [{"x": 1}, {"x": 2}, {"x": 3}]
        assert not e.exact_match(candidate, gold)
        assert e.answer_set_f1(candidate, gold) == 0.8  # 2*2/(3+2)

    def test_disjoint_scores_zero(self):
        assert e.answer_set_f1([{"x": 9}], [{"x": 1}]) == 0.0

    def test_both_empty_scores_one(self):
        assert e.answer_set_f1([], []) == 1.0


# --- refusal handling -----------------------------------------------------------


class TestRefusal:
    def test_fallback_counts_as_refusal(self):
        assert e.is_refusal({"fallback": True, "cypher": None})

    def test_refusal_contract_detected(self):
        assert e.is_refusal({"fallback": False, "cypher": "RETURN  null  LIMIT 0"})

    def test_normal_cypher_is_not_refusal(self):
        assert not e.is_refusal({"fallback": False, "cypher": "MATCH (n) RETURN n LIMIT 5"})

    def test_unanswerable_row_credits_refusal(self):
        case = {"question": "q", "unanswerable": True}
        scored = e.score_case(case, {"fallback": True, "iterations": 1}, [])
        assert scored["correct"] is True

    def test_unanswerable_row_penalizes_hallucinated_answer(self):
        case = {"question": "q", "unanswerable": True}
        candidate = {"fallback": False, "cypher": "MATCH (n:Incident) RETURN n", "rows": [{"n": 1}]}
        scored = e.score_case(case, candidate, [])
        assert scored["correct"] is False

    def test_answerable_row_penalizes_refusal(self):
        case = {"question": "q"}
        scored = e.score_case(case, {"fallback": True, "rows": [], "iterations": 3}, [{"n": 1}])
        assert scored["correct"] is False
        assert scored["f1"] == 0.0


# --- evaluate + aggregate ---------------------------------------------------------


CASES = [
    {"question": "answerable", "gold_cypher": "MATCH ..."},
    {"question": "impossible", "gold_cypher": "RETURN NULL LIMIT 0", "unanswerable": True},
]


def fake_run_agent(question):
    if question == "impossible":
        return {"fallback": False, "cypher": "RETURN NULL LIMIT 0", "rows": [], "iterations": 1}
    return {
        "fallback": False,
        "cypher": "MATCH (c:Company) RETURN c.name, count(*) LIMIT 25",
        "rows": [{"company": "Waymo", "n": 3}],
        "iterations": 2,
    }


def fake_run_gold(cypher):
    return [{"company": "Waymo", "n": 3}]


class TestEvaluate:
    def test_end_to_end_with_fakes(self):
        result = e.evaluate(CASES, fake_run_agent, fake_run_gold)
        m = result["metrics"]
        assert m["n"] == 2
        assert m["accuracy"] == 1.0
        assert m["refusal_precision"] == 1.0
        assert m["refusal_recall"] == 1.0
        assert m["mean_iterations"] == 1.5

    def test_summary_is_deterministic(self, tmp_path):
        result = e.evaluate(CASES, fake_run_agent, fake_run_gold)
        p1, _ = e.write_summary(result["metrics"], "t", out_dir=tmp_path, inputs={"split": "dev"})
        first = p1.read_text(encoding="utf-8")
        p2, _ = e.write_summary(result["metrics"], "t", out_dir=tmp_path, inputs={"split": "dev"})
        assert p2.read_text(encoding="utf-8") == first
        payload = json.loads(first)
        assert payload["metrics"]["accuracy"] == 1.0
