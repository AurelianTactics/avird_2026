"""RAG agent: grounded generation + faithfulness self-check (plan P2, U10).

The reusable loop shape (U4) again, with a different backend and **two tiers of
validation** that are the whole point of the phase:

    embed_query -> retrieve -> assemble -> generate -> validate_citations
                                  ^                          |
                                  |  (re-retrieve, bigger k)  v
                              fallback <--(budget/err)--  faithfulness_judge -> respond

1. **Citation existence** is the cheap, deterministic, always-on structural gate:
   every ``[n]`` the model emits must resolve to a retrieved chunk (via the U9
   ``id_map``). A fabricated ``[9]`` is caught and either repaired or stripped —
   a made-up citation never leaves the agent. (The analogue of P1's read-only
   role: trust the structure, not the model.)
2. **Faithfulness** is the expensive, model-judged tier (a larger model per
   KTD-7, the debate-judge pattern generalized): is every claim actually backed
   by a cited narrative? On unsupported claims the agent re-retrieves with a
   larger ``k`` and regenerates, bounded by ``max_iterations`` + budget.

Everything is injected behind a ``Protocol`` (embedding model, answer model,
judge model, store, budget guard) with fakes, so the loop runs key-free and
network-free in tests. The judge is optional: omit it and only the structural
citation gate runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from .context import ContextBlock, build_context
from .store import RetrievedChunk, Store

logger = logging.getLogger(__name__)

for _name in ("langgraph", "langchain", "langchain_core", "anthropic", "httpx"):
    logging.getLogger(_name).setLevel(logging.WARNING)

ANSWER_MODEL = "claude-haiku-4-5"
JUDGE_MODEL = "claude-sonnet-4-6"  # reasoning quality > latency for the judge (KTD-7)

DEFAULT_K = 5
MAX_ITERATIONS = 2
REFUSAL_TEXT = "NOT SUPPORTED BY THE DATA"

_CITATION_RE = re.compile(r"\[(\d+)\]")

_FALLBACK_MESSAGE = "The narrative-RAG service is unavailable right now."
_BUDGET_MESSAGE = "The narrative-RAG service is busy right now — try again later."

ANSWER_SYSTEM = (
    "You answer questions about autonomous-vehicle crash incidents using ONLY the "
    "numbered narratives provided.\n"
    "Rules:\n"
    "  - Cite the incidents you used with their number in square brackets, e.g. [2].\n"
    "  - Use only the numbers that appear in the context; never invent a citation.\n"
    f"  - If the narratives do not support an answer, reply exactly: {REFUSAL_TEXT}\n"
    "  - Be concise and ground every claim in a cited narrative.\n"
)

JUDGE_SYSTEM = (
    "You check whether an answer is faithful to the provided narratives. A claim "
    "is unsupported if no cited narrative backs it. Reply with ONLY a JSON object: "
    '{"supported": true|false, "unsupported": ["<claim>", ...]}. No prose.'
)


# --- seams ------------------------------------------------------------------


class EmbeddingModel(Protocol):
    def embed(self, text: str) -> Any: ...


class RagModel(Protocol):
    def answer(self, system: str, user: str) -> str: ...


class JudgeModel(Protocol):
    def judge(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class Faithfulness:
    supported: bool
    unsupported: list[str]


def parse_citations(answer: str) -> list[int]:
    """Every ``[n]`` integer cited in the answer, de-duplicated, in order."""
    seen: list[int] = []
    for m in _CITATION_RE.finditer(answer or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def resolve_citations(answer: str, id_map: dict[int, str]) -> tuple[list[str], list[int]]:
    """Split cited numbers into (resolved incident ids, invalid numbers)."""
    resolved: list[str] = []
    invalid: list[int] = []
    for n in parse_citations(answer):
        if n in id_map:
            resolved.append(id_map[n])
        else:
            invalid.append(n)
    return resolved, invalid


def strip_invalid_citations(answer: str, id_map: dict[int, str]) -> str:
    """Remove any ``[n]`` not in ``id_map`` — a fabricated citation never ships."""
    return _CITATION_RE.sub(lambda m: m.group(0) if int(m.group(1)) in id_map else "", answer)


def parse_faithfulness(raw: str) -> Faithfulness:
    """Lenient parse of the judge's JSON verdict; unparseable => treat supported."""
    try:
        text = raw.strip()
        start, end = text.find("{"), text.rfind("}")
        obj = json.loads(text[start : end + 1]) if start >= 0 else {}
        return Faithfulness(
            supported=bool(obj.get("supported", True)),
            unsupported=list(obj.get("unsupported", []) or []),
        )
    except Exception:  # noqa: BLE001
        return Faithfulness(supported=True, unsupported=[])


# --- real adapters (lazy imports; never needed by tests) --------------------


class BgeEmbeddingModel:
    """Real query embedder via HF Inference Providers (BAAI/bge-base-en-v1.5).

    Lazy: ``huggingface_hub`` and ``HF_TOKEN`` are only touched on first
    ``embed``, so importing this module needs neither. Mirrors
    ``eda/eda_utils_embed`` so the query vector matches the cached corpus vectors.
    """

    def __init__(self, *, model_id: str = "BAAI/bge-base-en-v1.5", client: Any = None):
        self._model_id = model_id
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            from huggingface_hub import InferenceClient

            self._client = InferenceClient(model=self._model_id, token=os.environ.get("HF_TOKEN"))
        return self._client

    def embed(self, text: str) -> Any:
        import numpy as np

        raw = self._ensure_client().feature_extraction(str(text).strip())
        arr = np.asarray(raw, dtype=np.float32)
        return arr.mean(axis=0) if arr.ndim == 2 else arr


class ClaudeRagModel:
    """Real answer model (Anthropic SDK). Constructed lazily — no key at import."""

    def __init__(self, *, model: str | None = None, client: Any = None):
        self._model = model or os.environ.get("RAG_ANSWER_MODEL") or ANSWER_MODEL
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def answer(self, system: str, user: str) -> str:
        resp = self._ensure_client().messages.create(
            model=self._model,
            max_tokens=700,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


class ClaudeJudgeModel:
    """Real faithfulness judge — a larger model than the answer model (KTD-7)."""

    def __init__(self, *, model: str | None = None, client: Any = None):
        self._model = model or os.environ.get("RAG_JUDGE_MODEL") or JUDGE_MODEL
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def judge(self, system: str, user: str) -> str:
        resp = self._ensure_client().messages.create(
            model=self._model,
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()


# --- graph state ------------------------------------------------------------


class RagState(TypedDict, total=False):
    question: str
    store: Store
    embedder: EmbeddingModel
    model: RagModel
    judge: Any  # JudgeModel | None
    guard: Any
    k: int
    max_iterations: int

    query_vec: Any
    retrieved: list[RetrievedChunk]
    context: ContextBlock
    iterations: int
    answer: str
    observation: str | None

    refused: bool
    supported: bool
    fallback: bool
    fallback_message: str
    result: dict[str, Any]


# --- nodes ------------------------------------------------------------------


async def embed_query(state: RagState) -> dict[str, Any]:
    try:
        vec = await asyncio.to_thread(state["embedder"].embed, state["question"])
    except Exception:  # noqa: BLE001
        logger.warning("rag: query embedding failed; using fallback")
        return {"fallback": True, "fallback_message": _FALLBACK_MESSAGE}
    return {"query_vec": vec, "iterations": 0, "k": state.get("k", DEFAULT_K)}


async def retrieve(state: RagState) -> dict[str, Any]:
    try:
        chunks = await state["store"].retrieve(state["query_vec"], state["k"], diversify=True)
    except Exception:  # noqa: BLE001
        logger.warning("rag: retrieval failed; using fallback")
        return {"fallback": True, "fallback_message": _FALLBACK_MESSAGE}
    return {"retrieved": chunks, "context": build_context(chunks)}


async def generate(state: RagState) -> dict[str, Any]:
    context = state["context"]
    if not context.chunks:
        # Nothing retrieved supports the question — a legitimate refusal, not an error.
        return {"answer": REFUSAL_TEXT, "refused": True, "supported": True}

    guard = state.get("guard")
    reservation = None
    if guard is not None:
        reservation = await guard.reserve(guard.estimate_cost())
        if reservation is None:
            return {"fallback": True, "fallback_message": _BUDGET_MESSAGE}

    user = _answer_prompt(state["question"], context, state.get("observation"))
    try:
        answer = await asyncio.to_thread(state["model"].answer, ANSWER_SYSTEM, user)
    except Exception:  # noqa: BLE001
        if guard is not None and reservation is not None:
            await guard.release(reservation)
        logger.warning("rag: answer model failed; using fallback")
        return {"fallback": True, "fallback_message": _FALLBACK_MESSAGE}

    answer = (answer or "").strip()
    refused = REFUSAL_TEXT.lower() in answer.lower()
    return {"answer": answer, "refused": refused, "iterations": state["iterations"] + 1}


def _answer_prompt(question: str, context: ContextBlock, observation: str | None) -> str:
    parts = ["Numbered narratives:", context.text, "", f"Question: {question}"]
    if observation:
        parts += ["", f"Revise your previous answer: {observation}"]
    parts.append("Answer:")
    return "\n".join(parts)


async def validate_citations(state: RagState) -> dict[str, Any]:
    _, invalid = resolve_citations(state["answer"], state["context"].id_map)
    if invalid:
        return {
            "observation": (
                f"you cited {invalid} which are not in the context; cite only the "
                "numbers shown, and only claims the narratives support"
            )
        }
    return {"observation": None}


async def faithfulness_judge(state: RagState) -> dict[str, Any]:
    judge = state.get("judge")
    if judge is None:
        return {"supported": True}

    guard = state.get("guard")
    reservation = None
    if guard is not None:
        reservation = await guard.reserve(guard.estimate_cost())
        if reservation is None:
            # Can't afford the judge — accept the citation-validated answer as-is.
            return {"supported": True}
    user = f"Narratives:\n{state['context'].text}\n\nAnswer:\n{state['answer']}"
    try:
        raw = await asyncio.to_thread(judge.judge, JUDGE_SYSTEM, user)
    except Exception:  # noqa: BLE001
        if guard is not None and reservation is not None:
            await guard.release(reservation)
        return {"supported": True}  # judge unavailable -> don't block the answer
    verdict = parse_faithfulness(raw)
    if not verdict.supported:
        return {
            "supported": False,
            "observation": (
                "the following claims were judged unsupported; remove them or ground "
                f"them in a cited narrative: {verdict.unsupported}"
            ),
        }
    return {"supported": True, "observation": None}


async def respond(state: RagState) -> dict[str, Any]:
    answer = strip_invalid_citations(state.get("answer", ""), state["context"].id_map)
    resolved, _ = resolve_citations(answer, state["context"].id_map)
    return {
        "result": {
            "question": state["question"],
            "answer": answer,
            "cited_incident_ids": resolved,
            "retrieved_ids": [c.incident_id for c in state.get("retrieved", [])],
            "supported": state.get("supported", True),
            "refused": state.get("refused", False),
            "iterations": state.get("iterations", 0),
            "fallback": False,
            "message": "",
        }
    }


async def fallback(state: RagState) -> dict[str, Any]:
    # Degrade to retrieval-only: "here are the most relevant incidents."
    retrieved = state.get("retrieved", [])
    return {
        "result": {
            "question": state["question"],
            "answer": "",
            "cited_incident_ids": [],
            "retrieved_ids": [c.incident_id for c in retrieved],
            "supported": False,
            "refused": False,
            "iterations": state.get("iterations", 0),
            "fallback": True,
            "message": state.get("fallback_message", _FALLBACK_MESSAGE),
        }
    }


# --- edges ------------------------------------------------------------------


def _max_iters(state: RagState) -> int:
    return state.get("max_iterations", MAX_ITERATIONS)


def _route_after(node_key: str):
    def _r(state: RagState) -> str:
        return "fallback" if state.get("fallback") else node_key

    return _r


def _route_after_generate(state: RagState) -> str:
    if state.get("fallback"):
        return "fallback"
    if state.get("refused"):
        return "respond"
    return "validate_citations"


def _route_after_validate(state: RagState) -> str:
    # Bad citations: repair if iterations remain, else accept (invalid ones get
    # stripped in respond) and move on to the faithfulness check.
    if state.get("observation") and state["iterations"] < _max_iters(state):
        return "generate"
    return "faithfulness_judge"


def _route_after_judge(state: RagState) -> str:
    if not state.get("supported") and state["iterations"] < _max_iters(state):
        return "broaden_retrieve"
    return "respond"


async def broaden_retrieve(state: RagState) -> dict[str, Any]:
    """Faithfulness repair: widen k and re-retrieve before regenerating."""
    return {"k": state["k"] * 2}


def _build_graph():
    builder = StateGraph(RagState)
    builder.add_node("embed_query", embed_query)
    builder.add_node("retrieve", retrieve)
    builder.add_node("generate", generate)
    builder.add_node("validate_citations", validate_citations)
    builder.add_node("faithfulness_judge", faithfulness_judge)
    builder.add_node("broaden_retrieve", broaden_retrieve)
    builder.add_node("respond", respond)
    builder.add_node("fallback", fallback)

    builder.add_edge(START, "embed_query")
    builder.add_conditional_edges(
        "embed_query", _route_after("retrieve"), {"retrieve": "retrieve", "fallback": "fallback"}
    )
    builder.add_conditional_edges(
        "retrieve", _route_after("generate"), {"generate": "generate", "fallback": "fallback"}
    )
    builder.add_conditional_edges(
        "generate",
        _route_after_generate,
        {
            "validate_citations": "validate_citations",
            "respond": "respond",
            "fallback": "fallback",
        },
    )
    builder.add_conditional_edges(
        "validate_citations",
        _route_after_validate,
        {"generate": "generate", "faithfulness_judge": "faithfulness_judge"},
    )
    builder.add_conditional_edges(
        "faithfulness_judge",
        _route_after_judge,
        {"broaden_retrieve": "broaden_retrieve", "respond": "respond"},
    )
    builder.add_edge("broaden_retrieve", "retrieve")
    builder.add_edge("respond", END)
    builder.add_edge("fallback", END)
    return builder.compile()


_GRAPH = _build_graph()


async def run_rag_query(
    question: str,
    *,
    store: Store,
    embedder: EmbeddingModel,
    model: RagModel,
    judge: Any = None,
    guard: Any = None,
    k: int = DEFAULT_K,
    max_iterations: int = MAX_ITERATIONS,
) -> dict[str, Any]:
    """Run the RAG graph. Always returns a renderable result dict:

    ``{question, answer, cited_incident_ids, retrieved_ids, supported, refused,
    iterations, fallback, message}``.

    Never raises: embedding/retrieval/model/judge failures route to ``fallback``
    (retrieval-only). ``judge`` is optional (structural citation gate only when
    omitted); ``guard`` is optional (no budget gating when omitted).
    """
    final = await _GRAPH.ainvoke(
        {
            "question": question or "",
            "store": store,
            "embedder": embedder,
            "model": model,
            "judge": judge,
            "guard": guard,
            "k": k,
            "max_iterations": max_iterations,
        }
    )
    return final["result"]


__all__ = [
    "ANSWER_MODEL",
    "JUDGE_MODEL",
    "BgeEmbeddingModel",
    "ClaudeJudgeModel",
    "ClaudeRagModel",
    "EmbeddingModel",
    "Faithfulness",
    "JudgeModel",
    "RagModel",
    "REFUSAL_TEXT",
    "parse_citations",
    "parse_faithfulness",
    "resolve_citations",
    "run_rag_query",
    "strip_invalid_citations",
]
