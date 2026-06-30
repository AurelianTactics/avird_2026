"""Tests for the nlsql eval harness (plan P1, U6).

The scoring core is pure: result-set equivalence (order-insensitive, floats
rounded), partial credit, refusal detection, and aggregation. The DB-backed
runner is exercised by hand against the seeded DB; here ``evaluate`` runs with
injected fakes. Also checks the held-out hygiene guard and summary determinism.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eval_nlsql as e

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


# --- result-set normalization + equality ------------------------------------


class TestEquality:
    def test_order_insensitive_match(self):
        a = [{"x": 1}, {"x": 2}]
        b = [{"x": 2}, {"x": 1}]
        assert e.exact_match(a, b)

    def test_float_rounding_match(self):
        a = [{"v": 0.123456789}]
        b = [{"v": 0.12345699}]
        assert e.exact_match(a, b)

    def test_value_based_ignores_column_names(self):
        # Candidate aliasing the count differently still matches on the numbers.
        a = [{"master_entity": "Waymo", "n": 3}]
        b = [{"master_entity": "Waymo", "count": 3}]
        assert e.exact_match(a, b)

    def test_different_results_do_not_match(self):
        assert not e.exact_match([{"x": 1}], [{"x": 2}])


class TestPartialCredit:
    def test_subset_scores_between_zero_and_one(self):
        gold = [{"x": 1}, {"x": 2}, {"x": 3}, {"x": 4}]
        cand = [{"x": 1}, {"x": 2}]
        pc = e.partial_credit(cand, gold)
        assert 0.0 < pc < 1.0

    def test_exact_scores_one(self):
        rows = [{"x": 1}, {"x": 2}]
        assert e.partial_credit(rows, rows) == 1.0

    def test_disjoint_scores_zero(self):
        assert e.partial_credit([{"x": 1}], [{"x": 9}]) == 0.0


# --- refusal detection ------------------------------------------------------


class TestRefusal:
    def test_fallback_is_refusal(self):
        assert e.is_refusal({"fallback": True, "sql": None})

    def test_refusal_sentinel_sql(self):
        assert e.is_refusal({"fallback": False, "sql": "SELECT NULL WHERE false"})
        assert e.is_refusal({"fallback": False, "sql": "select  null  where  false"})

    def test_normal_sql_is_not_refusal(self):
        assert not e.is_refusal(
            {"fallback": False, "sql": "SELECT COUNT(*) AS n FROM treated_incident_reports"}
        )


# --- score_case -------------------------------------------------------------


class TestScoreCase:
    def test_unanswerable_refused_is_correct(self):
        case = {"question": "q", "unanswerable": True}
        s = e.score_case(case, {"fallback": False, "sql": "SELECT NULL WHERE false"}, [])
        assert s["correct"] and s["refused"]

    def test_unanswerable_answered_is_wrong(self):
        case = {"question": "q", "unanswerable": True}
        s = e.score_case(case, {"fallback": False, "sql": "SELECT 1", "rows": [{"x": 1}]}, [])
        assert not s["correct"]

    def test_answerable_exact_is_correct(self):
        case = {"question": "q", "gold_sql": "SELECT 1"}
        cand = {"fallback": False, "sql": "SELECT 1", "rows": [{"n": 5}], "iterations": 1}
        s = e.score_case(case, cand, [{"n": 5}])
        assert s["correct"] and s["partial"] == 1.0

    def test_answerable_subset_is_partial_not_correct(self):
        case = {"question": "q", "gold_sql": "SELECT 1"}
        cand = {"fallback": False, "sql": "SELECT 1", "rows": [{"x": 1}], "iterations": 2}
        s = e.score_case(case, cand, [{"x": 1}, {"x": 2}])
        assert not s["correct"]
        assert 0.0 < s["partial"] < 1.0

    def test_answerable_refusal_is_wrong(self):
        case = {"question": "q", "gold_sql": "SELECT 1"}
        cand = {"fallback": True, "sql": None, "rows": [], "iterations": 3}
        s = e.score_case(case, cand, [{"x": 1}])
        assert not s["correct"]


# --- evaluate (injected fakes) + determinism --------------------------------


class TestEvaluate:
    def _cases(self):
        return [
            {"question": "count", "gold_sql": "G1"},
            {"question": "bad", "unanswerable": True},
        ]

    def _run_agent(self, question):
        if question == "count":
            return {"fallback": False, "sql": "SELECT 1", "rows": [{"n": 7}], "iterations": 1}
        return {"fallback": True, "sql": None, "rows": [], "iterations": 1}

    def _run_gold(self, sql):
        return [{"n": 7}]

    def test_metrics_shape_and_values(self):
        out = e.evaluate(self._cases(), self._run_agent, self._run_gold)
        m = out["metrics"]
        assert m["n"] == 2
        assert m["accuracy"] == 1.0  # the one answerable case matched
        assert m["refusal_precision"] == 1.0  # the only refusal was correct
        assert m["refusal_recall"] == 1.0

    def test_summary_is_deterministic(self, tmp_path):
        out = e.evaluate(self._cases(), self._run_agent, self._run_gold)
        p1, _ = e.write_summary(out["metrics"], "t", out_dir=tmp_path / "a")
        p2, _ = e.write_summary(out["metrics"], "t", out_dir=tmp_path / "b")
        assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")


# --- the committed golden files load + are well-formed ----------------------


class TestGoldenFiles:
    @pytest.mark.parametrize("split", ["dev", "heldout"])
    def test_rows_well_formed(self, split):
        path = REPO_ROOT / "golden" / "nlsql" / f"{split}.jsonl"
        rows = e.load_jsonl(path)
        assert len(rows) >= 10
        for r in rows:
            assert "question" in r and "gold_sql" in r
            if not r.get("unanswerable"):
                assert "kind" in r
            # every line is valid JSON with a non-empty question
            assert r["question"].strip()

    def test_dev_has_unanswerable_rows(self):
        rows = e.load_jsonl(REPO_ROOT / "golden" / "nlsql" / "dev.jsonl")
        assert any(r.get("unanswerable") for r in rows)
