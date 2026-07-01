"""Tests for the RAG eval harness (plan P2, U11).

Pure scoring: citation recall/precision (skipping unlabeled rows), keyword
coverage, refusal handling, and aggregation. The DB/agent-backed runner is run by
hand; here ``evaluate`` uses an injected fake.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import eval_rag as e

REPO_ROOT = Path(__file__).resolve().parents[2]


# --- citation metrics -------------------------------------------------------


class TestCitationMetrics:
    def test_perfect_recall_and_precision(self):
        m = e.citation_metrics(["a", "b"], ["a", "b"])
        assert m == {"recall": 1.0, "precision": 1.0}

    def test_extra_citation_drops_precision_not_recall(self):
        m = e.citation_metrics(["a", "b", "z"], ["a", "b"])
        assert m["recall"] == 1.0
        assert m["precision"] < 1.0

    def test_missing_citation_drops_recall(self):
        m = e.citation_metrics(["a"], ["a", "b"])
        assert m["recall"] == 0.5

    def test_unlabeled_row_returns_none(self):
        assert e.citation_metrics(["a"], []) is None


# --- answer-point coverage --------------------------------------------------


class TestCoverage:
    def test_full_coverage(self):
        assert (
            e.answer_point_coverage("a pedestrian in the crosswalk", ["pedestrian", "crosswalk"])
            == 1.0
        )

    def test_partial_coverage(self):
        assert e.answer_point_coverage("a pedestrian appeared", ["pedestrian", "crosswalk"]) == 0.5

    def test_case_insensitive(self):
        assert e.answer_point_coverage("REAR-ENDED while STOPPED", ["rear-ended", "stopped"]) == 1.0

    def test_no_points_returns_none(self):
        assert e.answer_point_coverage("anything", []) is None


# --- score_case + aggregate -------------------------------------------------


class TestScoreCase:
    def test_unsupported_refused_is_correct(self):
        s = e.score_case({"question": "q", "unsupported": True}, {"refused": True})
        assert s["correct"]

    def test_unsupported_answered_is_wrong(self):
        s = e.score_case(
            {"question": "q", "unsupported": True},
            {"refused": False, "fallback": False, "answer": "made up", "cited_incident_ids": []},
        )
        assert not s["correct"]

    def test_answerable_scores_citation_and_coverage(self):
        case = {
            "question": "q",
            "expected_incident_ids": ["a"],
            "answer_points": ["pedestrian"],
        }
        cand = {"cited_incident_ids": ["a"], "answer": "a pedestrian", "refused": False}
        s = e.score_case(case, cand)
        assert s["citation"]["recall"] == 1.0
        assert s["coverage"] == 1.0


class TestAggregate:
    def _run_agent(self, question):
        # The labeled question cites correctly; the unsupported one refuses.
        if "rear" in question:
            return {"cited_incident_ids": ["a"], "answer": "rear-ended", "refused": False}
        return {"refused": True, "fallback": False}

    def test_metrics_over_mixed_set(self):
        cases = [
            {
                "question": "rear-ended crash",
                "expected_incident_ids": ["a"],
                "answer_points": ["rear-ended"],
            },
            {"question": "unanswerable", "unsupported": True},
        ]
        out = e.evaluate(cases, self._run_agent)
        m = out["metrics"]
        assert m["n_labeled"] == 1
        assert m["mean_citation_recall"] == 1.0
        assert m["mean_answer_coverage"] == 1.0
        assert m["refusal_precision"] == 1.0
        assert m["refusal_recall"] == 1.0

    def test_unlabeled_rows_excluded_from_citation_mean(self):
        cases = [
            {"question": "x", "expected_incident_ids": [], "answer_points": ["foo"]},
        ]
        out = e.evaluate(cases, lambda q: {"cited_incident_ids": [], "answer": "foo bar"})
        assert out["metrics"]["n_labeled"] == 0
        assert out["metrics"]["mean_answer_coverage"] == 1.0


# --- committed golden files -------------------------------------------------


class TestGoldenFiles:
    @pytest.mark.parametrize("split", ["dev", "heldout"])
    def test_rows_well_formed(self, split):
        rows = e.load_jsonl(REPO_ROOT / "golden" / "rag" / f"{split}.jsonl")
        assert len(rows) >= 8
        for r in rows:
            assert r["question"].strip()
            if not r.get("unsupported"):
                assert "expected_incident_ids" in r and "answer_points" in r

    def test_has_unsupported_rows(self):
        rows = e.load_jsonl(REPO_ROOT / "golden" / "rag" / "dev.jsonl")
        assert any(r.get("unsupported") for r in rows)

    def test_heldout_refused_without_flag(self):
        with pytest.raises(PermissionError):
            e.golden_split_path("heldout", golden_dir=e.RAG_GOLDEN_DIR)
