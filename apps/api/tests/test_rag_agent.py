"""Tests for the RAG agent (plan P2, U10).

The two validation tiers are the contract: a fabricated citation never leaves the
agent (structural gate), and the faithfulness loop is observable (model-judged
tier). Everything is faked — no embeddings model, no Anthropic, no Postgres.
"""

from __future__ import annotations

from app.derived.budget import InMemoryBudgetGuard
from app.rag.agent import (
    REFUSAL_TEXT,
    parse_citations,
    resolve_citations,
    run_rag_query,
    strip_invalid_citations,
)
from app.rag.store import RetrievedChunk


class FakeStore:
    """Returns a fixed set of chunks (ids inc-1..inc-N) regardless of query."""

    def __init__(self, n=3, *, empty=False, raises=False):
        self._n = n
        self._empty = empty
        self._raises = raises

    async def retrieve(self, query_embedding, k, *, diversify=False):
        if self._raises:
            raise RuntimeError("store down")
        if self._empty:
            return []
        return [
            RetrievedChunk(f"inc-{i}", f"narrative {i}", 0.1 * i) for i in range(1, self._n + 1)
        ]


class FakeEmbedder:
    def __init__(self, *, raises=False):
        self._raises = raises

    def embed(self, text):
        if self._raises:
            raise RuntimeError("HF down")
        return [0.1, 0.2, 0.3]


class FakeModel:
    """Returns queued answers in order (or raises)."""

    def __init__(self, *, answers=None, raises=False):
        self._answers = list(answers or [])
        self._raises = raises
        self.calls = 0

    def answer(self, system, user):
        self.calls += 1
        if self._raises:
            raise RuntimeError("answer model down")
        return self._answers.pop(0) if self._answers else "no citation"


class FakeJudge:
    """Returns queued JSON verdicts in order."""

    def __init__(self, *, verdicts=None, raises=False):
        self._verdicts = list(verdicts or [])
        self._raises = raises
        self.calls = 0

    def judge(self, system, user):
        self.calls += 1
        if self._raises:
            raise RuntimeError("judge down")
        return self._verdicts.pop(0) if self._verdicts else '{"supported": true}'


# --- pure helpers -----------------------------------------------------------


class TestCitationHelpers:
    def test_parse_and_resolve(self):
        id_map = {1: "inc-1", 2: "inc-2"}
        resolved, invalid = resolve_citations("see [1] and [2]", id_map)
        assert resolved == ["inc-1", "inc-2"] and invalid == []

    def test_invalid_citation_detected(self):
        resolved, invalid = resolve_citations("see [9]", {1: "inc-1"})
        assert resolved == [] and invalid == [9]

    def test_strip_removes_only_invalid(self):
        out = strip_invalid_citations("a [1] b [9] c", {1: "inc-1"})
        assert "[1]" in out and "[9]" not in out

    def test_parse_dedupes(self):
        assert parse_citations("[1] [1] [2]") == [1, 2]


# --- happy path -------------------------------------------------------------


async def test_valid_citations_pass_and_judge_approves():
    store = FakeStore(n=3)
    model = FakeModel(answers=["The crash involved a pedestrian [1][3]."])
    judge = FakeJudge(verdicts=['{"supported": true}'])
    result = await run_rag_query(
        "what happened?", store=store, embedder=FakeEmbedder(), model=model, judge=judge
    )
    assert result["fallback"] is False
    assert result["cited_incident_ids"] == ["inc-1", "inc-3"]
    assert result["supported"] is True
    assert judge.calls == 1


# --- citation gate ----------------------------------------------------------


async def test_fabricated_citation_repaired_then_clean():
    # First answer cites [9] (not retrieved); repair yields a valid citation.
    store = FakeStore(n=3)
    model = FakeModel(answers=["bad [9]", "good [2]"])
    result = await run_rag_query(
        "q", store=store, embedder=FakeEmbedder(), model=model, max_iterations=2
    )
    assert result["cited_incident_ids"] == ["inc-2"]
    # A fabricated citation never appears in the final answer.
    assert "[9]" not in result["answer"]
    assert model.calls == 2


async def test_fabricated_citation_stripped_when_iterations_exhausted():
    # Model keeps citing [9]; after the bound, the invalid citation is stripped.
    store = FakeStore(n=3)
    model = FakeModel(answers=["bad [9]", "still bad [9]", "[9] again"])
    result = await run_rag_query(
        "q", store=store, embedder=FakeEmbedder(), model=model, max_iterations=2
    )
    assert "[9]" not in result["answer"]
    assert result["cited_incident_ids"] == []


# --- faithfulness loop ------------------------------------------------------


async def test_unsupported_claim_triggers_one_repair_then_approved():
    store = FakeStore(n=3)
    model = FakeModel(answers=["claim [1]", "fixed claim [1]"])
    judge = FakeJudge(
        verdicts=['{"supported": false, "unsupported": ["x"]}', '{"supported": true}']
    )
    result = await run_rag_query(
        "q", store=store, embedder=FakeEmbedder(), model=model, judge=judge, max_iterations=2
    )
    assert result["supported"] is True
    assert judge.calls == 2
    assert model.calls == 2


async def test_persistently_unfaithful_stops_at_bound():
    store = FakeStore(n=3)
    model = FakeModel(answers=["[1]", "[1]", "[1]", "[1]"])
    judge = FakeJudge(verdicts=['{"supported": false, "unsupported": ["x"]}'] * 4)
    result = await run_rag_query(
        "q", store=store, embedder=FakeEmbedder(), model=model, judge=judge, max_iterations=2
    )
    # Bounded: at most max_iterations answer attempts.
    assert model.calls == 2
    assert result["supported"] is False


# --- refusal ----------------------------------------------------------------


async def test_empty_retrieval_refuses():
    store = FakeStore(empty=True)
    model = FakeModel(answers=["should not be called"])
    result = await run_rag_query("q", store=store, embedder=FakeEmbedder(), model=model)
    assert result["refused"] is True
    assert REFUSAL_TEXT in result["answer"]
    assert model.calls == 0  # never generated — nothing to ground on


async def test_model_says_not_supported_is_refusal():
    store = FakeStore(n=2)
    model = FakeModel(answers=[REFUSAL_TEXT])
    result = await run_rag_query("q", store=store, embedder=FakeEmbedder(), model=model)
    assert result["refused"] is True
    assert result["fallback"] is False


# --- error / budget ---------------------------------------------------------


async def test_embedding_failure_falls_back():
    result = await run_rag_query(
        "q", store=FakeStore(), embedder=FakeEmbedder(raises=True), model=FakeModel()
    )
    assert result["fallback"] is True
    assert "unavailable" in result["message"].lower()


async def test_store_failure_falls_back():
    result = await run_rag_query(
        "q", store=FakeStore(raises=True), embedder=FakeEmbedder(), model=FakeModel()
    )
    assert result["fallback"] is True


async def test_budget_trip_degrades_to_retrieval_only():
    store = FakeStore(n=3)
    model = FakeModel(answers=["[1]"])
    guard = InMemoryBudgetGuard(daily_limit_usd=0.0)
    result = await run_rag_query(
        "q", store=store, embedder=FakeEmbedder(), model=model, guard=guard
    )
    assert result["fallback"] is True
    # Retrieval-only fallback still surfaces the relevant incidents.
    assert result["retrieved_ids"] == ["inc-1", "inc-2", "inc-3"]
    assert model.calls == 0


async def test_judge_unavailable_does_not_block_answer():
    store = FakeStore(n=2)
    model = FakeModel(answers=["answer [1]"])
    judge = FakeJudge(raises=True)
    result = await run_rag_query(
        "q", store=store, embedder=FakeEmbedder(), model=model, judge=judge
    )
    # Judge raised, but the citation-validated answer still ships.
    assert result["fallback"] is False
    assert result["cited_incident_ids"] == ["inc-1"]


async def test_result_shape_has_all_keys():
    result = await run_rag_query(
        "q", store=FakeStore(n=1), embedder=FakeEmbedder(), model=FakeModel(answers=["[1]"])
    )
    assert set(result) >= {
        "question",
        "answer",
        "cited_incident_ids",
        "retrieved_ids",
        "supported",
        "refused",
        "iterations",
        "fallback",
        "message",
    }


# --- CLI smoke (plan P2, U10) -----------------------------------------------


def test_cli_help_exits_zero(capsys):
    import pytest

    from app.rag import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "question" in capsys.readouterr().out.lower()


def test_cli_stubbed_run_exits_zero(capsys):
    from app.rag import cli

    code = cli.main(
        ["what happened at night?"],
        store=FakeStore(n=2),
        embedder=FakeEmbedder(),
        model=FakeModel(answers=["A crash at night [1]."]),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "cited incidents" in out
    assert "inc-1" in out
