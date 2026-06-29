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
# Output cap per call — also the advocate/judge ``max_tokens`` and the output
# half of the budget reservation estimate, so the cap and the estimate can't
# drift apart.
MAX_OUTPUT_TOKENS = _int_env("DEBATE_MAX_OUTPUT_TOKENS", 600)

BUDGET_MESSAGE = "AI debates are taking a break — try again later."

# --- Budget guard ----------------------------------------------------------

# claude-haiku-4-5 pricing: $1.00 / MTok input, $5.00 / MTok output.
HAIKU_INPUT_USD_PER_TOKEN = 1.00 / 1_000_000
HAIKU_OUTPUT_USD_PER_TOKEN = 5.00 / 1_000_000
WINDOW_SECONDS = 24 * 60 * 60
# Conservative input size for a single call's cost estimate: every input cap
# maxed out, plus slack for the incident text + prompt scaffold, at ~4 chars
# per token. Used to *reserve* budget before a call, when the real token count
# isn't known yet.
_ESTIMATE_INPUT_CHARS = MAX_TRANSCRIPT_CHARS + MAX_ARGUMENT_CHARS + 4000
_CHARS_PER_TOKEN = 4


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
    """Rolling-window USD spend cap with **reserve-then-check** semantics.

    A call first ``reserve()``s its *estimated* worst-case cost; the reservation
    is committed and counted against the window before the paid call runs, so
    concurrent requests see each other and can't all slip past the cap at once
    (the gap the old check-then-spend guard left open). After the call,
    ``reconcile()`` rewrites the reservation to the *actual* token cost, or
    ``release()`` drops it if the call failed.

    Subclasses provide storage: :class:`InMemoryBudgetGuard` (process-local,
    used by tests) and :class:`DbBudgetGuard` (durable, shared across restarts
    and instances — the production default).
    """

    def __init__(
        self,
        daily_limit_usd: float | None = None,
        *,
        window_seconds: int = WINDOW_SECONDS,
        input_price: float = HAIKU_INPUT_USD_PER_TOKEN,
        output_price: float = HAIKU_OUTPUT_USD_PER_TOKEN,
    ):
        self.daily_limit = _default_budget_usd() if daily_limit_usd is None else daily_limit_usd
        self.window_seconds = window_seconds
        self.input_price = input_price
        self.output_price = output_price

    def cost(self, usage: Usage) -> float:
        return usage.input_tokens * self.input_price + usage.output_tokens * self.output_price

    def estimate_cost(self) -> float:
        """Worst-case USD for one call — reserved up front, before token counts
        are known. Uses this guard's prices so the estimate tracks them."""
        est_input_tokens = _ESTIMATE_INPUT_CHARS / _CHARS_PER_TOKEN
        return est_input_tokens * self.input_price + MAX_OUTPUT_TOKENS * self.output_price

    async def reserve(self, estimated_cost: float) -> int | None:  # pragma: no cover
        raise NotImplementedError

    async def reconcile(self, reservation: int, usage: Usage) -> None:  # pragma: no cover
        raise NotImplementedError

    async def release(self, reservation: int) -> None:  # pragma: no cover
        raise NotImplementedError


class InMemoryBudgetGuard(BudgetGuard):
    """Process-local guard. Correct for a single instance but does **not**
    survive restarts or coordinate across instances — that's what
    :class:`DbBudgetGuard` is for. Kept as the test seam (no DB needed)."""

    def __init__(self, *args, now=time.monotonic, **kwargs):
        super().__init__(*args, **kwargs)
        self._now = now
        self._events: dict[int, tuple[float, float]] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def _spent_locked(self, t: float) -> float:
        cutoff = t - self.window_seconds
        for rid in [k for k, (ts, _) in self._events.items() if ts < cutoff]:
            del self._events[rid]
        return sum(cost for _, cost in self._events.values())

    def spent(self) -> float:
        with self._lock:
            return self._spent_locked(self._now())

    async def reserve(self, estimated_cost: float) -> int | None:
        with self._lock:
            t = self._now()
            if self._spent_locked(t) + estimated_cost > self.daily_limit:
                return None
            self._seq += 1
            self._events[self._seq] = (t, estimated_cost)
            return self._seq

    async def reconcile(self, reservation: int, usage: Usage) -> None:
        with self._lock:
            event = self._events.get(reservation)
            if event is not None:
                self._events[reservation] = (event[0], self.cost(usage))

    async def release(self, reservation: int) -> None:
        with self._lock:
            self._events.pop(reservation, None)


class DbBudgetGuard(BudgetGuard):
    """Durable guard backed by a ``debate_spend`` ledger in Postgres. Survives
    api restarts and is correct across multiple instances. The reserve check +
    insert run under a transaction-scoped advisory lock so concurrent callers
    serialize on the spend total — no overshoot. The table is created lazily
    (``IF NOT EXISTS``) on first use; it's operational state owned by the api,
    not part of the crash-data pipeline."""

    # Arbitrary 64-bit key; all reservations contend on the same advisory lock.
    _LOCK_KEY = 0x4156_4244_4753  # "AVBDGS"

    def __init__(self, *args, pool_getter=None, **kwargs):
        super().__init__(*args, **kwargs)
        if pool_getter is None:
            from .db import get_pool

            pool_getter = get_pool
        self._pool_getter = pool_getter
        self._table_ready = False

    async def _ensure_table(self, conn) -> None:
        if self._table_ready:
            return
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS debate_spend ("
            "  id BIGSERIAL PRIMARY KEY,"
            "  ts timestamptz NOT NULL DEFAULT now(),"
            "  cost_usd double precision NOT NULL)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS debate_spend_ts_idx ON debate_spend (ts)")
        self._table_ready = True

    async def reserve(self, estimated_cost: float) -> int | None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await self._ensure_table(conn)
            async with conn.transaction():
                # Serialize concurrent reservations; lock auto-releases at commit.
                await conn.execute("SELECT pg_advisory_xact_lock($1)", self._LOCK_KEY)
                spent = await conn.fetchval(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM debate_spend "
                    "WHERE ts > now() - make_interval(secs => $1)",
                    float(self.window_seconds),
                )
                if float(spent) + estimated_cost > self.daily_limit:
                    return None
                return await conn.fetchval(
                    "INSERT INTO debate_spend (cost_usd) VALUES ($1) RETURNING id",
                    estimated_cost,
                )

    async def reconcile(self, reservation: int, usage: Usage) -> None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE debate_spend SET cost_usd = $1 WHERE id = $2",
                self.cost(usage),
                reservation,
            )

    async def release(self, reservation: int) -> None:
        pool = await self._pool_getter()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM debate_spend WHERE id = $1", reservation)


_budget_guard: BudgetGuard = DbBudgetGuard()


def get_budget_guard() -> BudgetGuard:
    """FastAPI dependency. Production uses the durable DB-backed guard; tests
    override with a low-cap :class:`InMemoryBudgetGuard`."""
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
        self,
        model_id: str | None = None,
        *,
        max_tokens: int = MAX_OUTPUT_TOKENS,
        temperature: float = 0.3,
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
    # Resolve the incident (404) before reserving budget, so a bad report id
    # never churns the ledger.
    incident_text = await _incident_text(report_id, data)

    reservation = await guard.reserve(guard.estimate_cost())
    if reservation is None:
        raise HTTPException(status_code=429, detail=BUDGET_MESSAGE)
    try:
        prompt = _advocate_prompt(
            incident_text, body.user_position, body.transcript, body.user_argument
        )
        graph = build_advocate_graph(client)
        state = await run_in_threadpool(
            graph.invoke, {"prompt": prompt, "message": None, "usage": None}
        )
        await guard.reconcile(reservation, state.get("usage") or Usage(0, 0))
        return {
            "message": state["message"],
            "ai_position": _opposite(body.user_position),
            "round": sum(1 for m in body.transcript if m.role == "user") + 1,
        }
    except Exception:
        # The call didn't bill (or we can't know its cost) — free the reservation.
        await guard.release(reservation)
        raise


@router.post("/incidents/{report_id}/debate/judge")
async def debate_judge(
    report_id: str,
    body: JudgeRequest,
    data: IncidentData = Depends(get_incident_data),
    client: AnthropicDebateClient = Depends(get_debate_client),
    guard: BudgetGuard = Depends(get_budget_guard),
) -> dict[str, Any]:
    _enforce_caps(body.transcript)
    incident_text = await _incident_text(report_id, data)

    reservation = await guard.reserve(guard.estimate_cost())
    if reservation is None:
        raise HTTPException(status_code=429, detail=BUDGET_MESSAGE)
    try:
        prompt = _judge_prompt(incident_text, body.transcript)
        graph = build_judge_graph(client)
        state = await run_in_threadpool(
            graph.invoke, {"prompt": prompt, "verdict": None, "usage": None}
        )
        await guard.reconcile(reservation, state.get("usage") or Usage(0, 0))
        return _coerce_verdict(state["verdict"])
    except Exception:
        await guard.release(reservation)
        raise
