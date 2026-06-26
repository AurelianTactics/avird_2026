"""Live, stateless AV-fault debate (Feature 2, covers R6/R7/R7a).

Two POST routes run a LangGraph pipeline at request time and persist nothing —
the browser holds the transcript and posts it back each turn:

- ``POST /incidents/{id}/debate/turn``  → one AI advocate message arguing the
  *opposite* side of the visitor's position.
- ``POST /incidents/{id}/debate/judge`` → a neutral verdict over the transcript.

Both bill paid Haiku calls and are reachable from the public ``web`` origin, so
hard caps (max rounds, per-argument length, total transcript size) and a
process-local USD budget guard gate every call (R7a). The LLM client and the
budget guard are injected via FastAPI dependencies that tests override, so the
suite runs with no network and no key.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .data import IncidentData, get_incident_data
from .incidents import _shape_detail

router = APIRouter()

# --- Caps (env-overridable) ------------------------------------------------


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


MAX_ROUNDS = _int_env("DEBATE_MAX_ROUNDS", 5)
MAX_ARGUMENT_CHARS = _int_env("DEBATE_MAX_ARGUMENT_CHARS", 2000)
MAX_TRANSCRIPT_CHARS = _int_env("DEBATE_MAX_TRANSCRIPT_CHARS", 20000)
# A transcript is user/ai pairs; allow a little slack over 2*rounds.
MAX_TRANSCRIPT_MESSAGES = 2 * MAX_ROUNDS + 2
MAX_REASONING_CHARS = 1500

BUDGET_MESSAGE = "AI debates are taking a break — try again later."

# --- Budget guard ----------------------------------------------------------

# claude-haiku-4-5 pricing: $1.00 / MTok input, $5.00 / MTok output.
HAIKU_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
HAIKU_OUTPUT_USD_PER_TOKEN = 5.00 / 1_000_000
WINDOW_SECONDS = 24 * 60 * 60


def _default_budget_usd() -> float:
    try:
        return float(os.environ.get("DEBATE_DAILY_BUDGET_USD", "5"))
    except (TypeError, ValueError):
        return 5.0


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int


class BudgetGuard:
    """Rolling 24h USD spend tracker. Process-local — good enough for a single
    small ``api`` instance; resets on restart (noted in the plan). Once the
    window's spend reaches the cap, ``exceeded()`` is True and routes 429."""

    def __init__(
        self,
        daily_limit_usd: float | None = None,
        *,
        window_seconds: int = WINDOW_SECONDS,
        input_price: float = HAIKU_INPUT_USD_PER_TOKEN,
        output_price: float = HAIKU_OUTPUT_USD_PER_TOKEN,
        now=time.monotonic,
    ):
        self.daily_limit = _default_budget_usd() if daily_limit_usd is None else daily_limit_usd
        self.window_seconds = window_seconds
        self.input_price = input_price
        self.output_price = output_price
        self._now = now
        self._events: deque[tuple[float, float]] = deque()
        self._lock = threading.Lock()

    def _trim(self, t: float) -> None:
        cutoff = t - self.window_seconds
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def spent(self) -> float:
        with self._lock:
            self._trim(self._now())
            return sum(cost for _, cost in self._events)

    def exceeded(self) -> bool:
        return self.spent() >= self.daily_limit

    def record(self, usage: Usage) -> float:
        cost = usage.input_tokens * self.input_price + usage.output_tokens * self.output_price
        with self._lock:
            t = self._now()
            self._trim(t)
            self._events.append((t, cost))
        return cost


_budget_guard = BudgetGuard()


def get_budget_guard() -> BudgetGuard:
    """FastAPI dependency. Tests override with a low-cap instance."""
    return _budget_guard


# --- LLM client seam -------------------------------------------------------


class JudgeVerdict(BaseModel):
    is_av_at_fault: bool = Field(description="True if the AV is primarily at fault.")
    fault_percentage: float = Field(description="The AV's share of fault, 0.0–1.0.")
    reasoning: str = Field(description="A short justification for the verdict.")


class AnthropicDebateClient:
    """Real ChatAnthropic-backed advocate/judge caller. Constructed lazily so
    importing this module (and the test suite) never needs a key or network."""

    def __init__(
        self, model_id: str | None = None, *, max_tokens: int = 600, temperature: float = 0.3
    ):
        self.model_id = model_id or os.environ.get("DEBATE_MODEL_ID", "claude-haiku-4-5")
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._chat = None

    def _client(self):
        if self._chat is None:
            from langchain_anthropic import ChatAnthropic

            self._chat = ChatAnthropic(
                model=self.model_id,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                timeout=60.0,
                max_retries=2,
            )
        return self._chat

    def advocate(self, prompt: str) -> tuple[str, Usage]:
        msg = self._client().invoke(prompt)
        return str(msg.content), _usage_from_message(msg)

    def judge(self, prompt: str) -> tuple[JudgeVerdict, Usage]:
        structured = self._client().with_structured_output(JudgeVerdict, include_raw=True)
        out = structured.invoke(prompt)
        verdict = out.get("parsed")
        if verdict is None:
            raise HTTPException(status_code=502, detail="judge returned no verdict")
        return verdict, _usage_from_message(out.get("raw"))


def _usage_from_message(msg) -> Usage:
    meta = getattr(msg, "usage_metadata", None) or {}
    return Usage(
        input_tokens=int(meta.get("input_tokens", 0) or 0),
        output_tokens=int(meta.get("output_tokens", 0) or 0),
    )


_debate_client = AnthropicDebateClient()


def get_debate_client() -> AnthropicDebateClient:
    """FastAPI dependency. Tests override with a stub returning canned output."""
    return _debate_client


# --- Request/response shapes -----------------------------------------------

Position = Literal["av_at_fault", "not_at_fault"]


class DebateMessage(BaseModel):
    role: Literal["user", "ai"]
    content: str


class TurnRequest(BaseModel):
    user_position: Position
    transcript: list[DebateMessage] = Field(default_factory=list)
    user_argument: str


class JudgeRequest(BaseModel):
    transcript: list[DebateMessage] = Field(default_factory=list)


def _opposite(position: Position) -> Position:
    return "not_at_fault" if position == "av_at_fault" else "av_at_fault"


def _enforce_caps(transcript: list[DebateMessage], user_argument: str | None = None) -> None:
    """Reject over-cap input with 400 before any paid call (R7a)."""
    if user_argument is not None and len(user_argument) > MAX_ARGUMENT_CHARS:
        raise HTTPException(status_code=400, detail="argument too long")
    if len(transcript) > MAX_TRANSCRIPT_MESSAGES:
        raise HTTPException(status_code=400, detail="transcript too long")
    total = sum(len(m.content) for m in transcript) + (len(user_argument or ""))
    if total > MAX_TRANSCRIPT_CHARS:
        raise HTTPException(status_code=400, detail="transcript too large")
    if user_argument is not None:
        user_rounds = sum(1 for m in transcript if m.role == "user")
        if user_rounds >= MAX_ROUNDS:
            raise HTTPException(status_code=400, detail="max rounds reached")


# --- Incident rendering ----------------------------------------------------

_DEBATE_FIELDS: list[tuple[str, str]] = [
    ("operating_entity", "Operating Entity"),
    ("incident_date", "Incident Date"),
    ("city", "City"),
    ("state", "State"),
    ("crash_with", "Crash With"),
    ("sv_pre_crash_movement", "AV Pre-Crash Movement"),
    ("cp_pre_crash_movement", "Other Party Pre-Crash Movement"),
    ("precrash_speed", "AV Pre-Crash Speed (MPH)"),
    ("roadway_type", "Roadway Type"),
    ("severity", "Highest Injury Severity"),
    ("property_damage", "Property Damage"),
]


def _render_incident(detail: dict[str, Any]) -> str:
    narrative = (detail.get("narrative") or "").strip() or "No narrative provided."
    lines = [f"Incident narrative:\n{narrative}", ""]
    facts = []
    for key, label in _DEBATE_FIELDS:
        value = (str(detail.get(key) or "")).strip()
        if value:
            facts.append(f"- {label}: {value}")
    if facts:
        lines.append("Structured details:")
        lines.extend(facts)
    return "\n".join(lines)


def _render_transcript(transcript: list[DebateMessage]) -> str:
    if not transcript:
        return "(no arguments yet)"
    rows = []
    for m in transcript:
        speaker = "Visitor" if m.role == "user" else "AI advocate"
        rows.append(f"{speaker}: {m.content}")
    return "\n\n".join(rows)


def _advocate_prompt(
    incident_text: str,
    user_position: Position,
    transcript: list[DebateMessage],
    user_argument: str,
) -> str:
    ai_position = _opposite(user_position)
    stance = (
        "the autonomous vehicle (AV) IS at fault"
        if ai_position == "av_at_fault"
        else "the autonomous vehicle (AV) is NOT at fault"
    )
    return (
        "You are an expert advocate in an autonomous-vehicle fault debate. Argue "
        f"that {stance} for this incident. Keep your argument concise (under 200 "
        "words), grounded in the specific facts, and respond to the visitor's "
        "latest point.\n\n"
        f"{incident_text}\n\n"
        f"Debate so far:\n{_render_transcript(transcript)}\n\n"
        f"Visitor's latest argument:\n{user_argument}\n\n"
        "Your rebuttal:"
    )


def _judge_prompt(incident_text: str, transcript: list[DebateMessage]) -> str:
    return (
        "You are a neutral judge in an autonomous-vehicle fault debate. Read the "
        "incident and the full debate, then render an impartial verdict: whether "
        "the AV is at fault, its fault share from 0.0 to 1.0, and a short "
        "reasoning.\n\n"
        f"{incident_text}\n\n"
        f"Full debate:\n{_render_transcript(transcript)}"
    )


# --- LangGraph pipelines (single node each) --------------------------------


class _AdvocateState(TypedDict):
    prompt: str
    message: str | None
    usage: Usage | None


class _JudgeState(TypedDict):
    prompt: str
    verdict: JudgeVerdict | None
    usage: Usage | None


def build_advocate_graph(client):
    from langgraph.graph import END, START, StateGraph

    def advocate(state: _AdvocateState) -> dict:
        message, usage = client.advocate(state["prompt"])
        return {"message": message, "usage": usage}

    builder = StateGraph(_AdvocateState)
    builder.add_node("advocate", advocate)
    builder.add_edge(START, "advocate")
    builder.add_edge("advocate", END)
    return builder.compile()


def build_judge_graph(client):
    from langgraph.graph import END, START, StateGraph

    def judge(state: _JudgeState) -> dict:
        verdict, usage = client.judge(state["prompt"])
        return {"verdict": verdict, "usage": usage}

    builder = StateGraph(_JudgeState)
    builder.add_node("judge", judge)
    builder.add_edge(START, "judge")
    builder.add_edge("judge", END)
    return builder.compile()


def _coerce_verdict(verdict: JudgeVerdict) -> dict[str, Any]:
    pct = verdict.fault_percentage
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        pct = 0.5
    pct = max(0.0, min(1.0, float(pct)))
    reasoning = (verdict.reasoning or "").strip()[:MAX_REASONING_CHARS]
    return {
        "is_av_at_fault": bool(verdict.is_av_at_fault),
        "fault_percentage": pct,
        "reasoning": reasoning,
    }


async def _incident_text(report_id: str, data: IncidentData) -> str:
    row = await data.fetch_incident(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")
    return _render_incident(_shape_detail(row))


# --- Routes ----------------------------------------------------------------


@router.post("/incidents/{report_id}/debate/turn")
async def debate_turn(
    report_id: str,
    body: TurnRequest,
    data: IncidentData = Depends(get_incident_data),
    client: AnthropicDebateClient = Depends(get_debate_client),
    guard: BudgetGuard = Depends(get_budget_guard),
) -> dict[str, Any]:
    _enforce_caps(body.transcript, body.user_argument)
    if guard.exceeded():
        raise HTTPException(status_code=429, detail=BUDGET_MESSAGE)

    incident_text = await _incident_text(report_id, data)
    prompt = _advocate_prompt(
        incident_text, body.user_position, body.transcript, body.user_argument
    )
    graph = build_advocate_graph(client)
    state = await run_in_threadpool(
        graph.invoke, {"prompt": prompt, "message": None, "usage": None}
    )
    if state.get("usage") is not None:
        guard.record(state["usage"])

    return {
        "message": state["message"],
        "ai_position": _opposite(body.user_position),
        "round": sum(1 for m in body.transcript if m.role == "user") + 1,
    }


@router.post("/incidents/{report_id}/debate/judge")
async def debate_judge(
    report_id: str,
    body: JudgeRequest,
    data: IncidentData = Depends(get_incident_data),
    client: AnthropicDebateClient = Depends(get_debate_client),
    guard: BudgetGuard = Depends(get_budget_guard),
) -> dict[str, Any]:
    _enforce_caps(body.transcript)
    if guard.exceeded():
        raise HTTPException(status_code=429, detail=BUDGET_MESSAGE)

    incident_text = await _incident_text(report_id, data)
    prompt = _judge_prompt(incident_text, body.transcript)
    graph = build_judge_graph(client)
    state = await run_in_threadpool(
        graph.invoke, {"prompt": prompt, "verdict": None, "usage": None}
    )
    if state.get("usage") is not None:
        guard.record(state["usage"])

    return _coerce_verdict(state["verdict"])
