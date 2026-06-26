'''Single-node LangGraph "neutral adjuster" that renders a structured verdict.

Mirrors the old Flask-era arbitrator node, but returns a *structured* verdict
via ``llm.py``'s ``CachedLLM.call(prompt, schema)`` instead of parsing JSON out
of free text. The graph is intentionally one node — the LangGraph wrapper is
kept for parity with the ontology track (and as the live-debate graph's
sibling), not because the judge needs branching.

``judge_incident`` returns ``(verdict, error)``:
- ``(FaultVerdict, None)`` on success,
- ``(None, None)`` on a dry-run cache miss (no spend),
- ``(None, "<reason>")`` on a permanent parse/validation failure — the batch
  turns this into the explicit error sentinel, never a guessed verdict.
'''
from __future__ import annotations

import sys
from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field

# Reuse the ontology track's content-addressed, retrying LLM client.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / 'ontology') not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / 'ontology'))

from llm import LLMCallError  # noqa: E402

PROMPT_VERSION = 'p001'

ADJUSTER_INSTRUCTIONS = (
    'You are a neutral insurance adjuster assessing an autonomous-vehicle (AV) '
    'crash. The "subject vehicle" (SV / AV) is the autonomous vehicle; the '
    '"other party" (CP) is whatever it crashed with. Read the incident below '
    'and decide whether the AV is at fault.\n\n'
    'Return your assessment with these fields:\n'
    '- is_av_at_fault: true if the AV bears primary responsibility, else false.\n'
    '- av_fault_percentage: the AV\'s share of fault as a number from 0.0 '
    '(not at all at fault) to 1.0 (entirely at fault).\n'
    '- short_explanation_of_decision: 1-3 sentences justifying the verdict '
    'using the specific facts of this incident.\n\n'
    'Be impartial and base the verdict only on the facts provided.'
)


class FaultVerdict(BaseModel):
    '''Structured adjuster verdict. Range/length are enforced by the batch's
    own validation (coerce_verdict), not by schema constraints, so a model that
    returns an out-of-range value surfaces as the error sentinel rather than a
    structured-output retry storm.'''

    is_av_at_fault: bool = Field(
        description='True if the autonomous vehicle is primarily at fault.'
    )
    av_fault_percentage: float = Field(
        description="The AV's share of fault, from 0.0 to 1.0."
    )
    short_explanation_of_decision: str = Field(
        description='A 1-3 sentence justification grounded in the incident facts.'
    )


def adjuster_prompt(incident_text: str) -> str:
    '''Compose the full adjuster prompt (instructions + rendered incident).'''
    return f'{ADJUSTER_INSTRUCTIONS}\n\n---\n\n{incident_text}'


class JudgeState(TypedDict):
    prompt: str
    verdict: FaultVerdict | None
    error: str | None


def build_graph(llm):
    '''Compile the one-node adjuster graph bound to a CachedLLM (or stub).'''
    from langgraph.graph import END, START, StateGraph

    def adjudicate(state: JudgeState) -> dict:
        try:
            verdict = llm.call(state['prompt'], FaultVerdict)
        except LLMCallError as e:
            # A permanent parse/validation failure must never become a guessed
            # verdict — record the reason and let the batch store the sentinel.
            return {'verdict': None, 'error': str(e)}
        return {'verdict': verdict, 'error': None}

    builder = StateGraph(JudgeState)
    builder.add_node('adjudicate', adjudicate)
    builder.add_edge(START, 'adjudicate')
    builder.add_edge('adjudicate', END)
    return builder.compile()


def judge_incident(graph, incident_text: str) -> tuple[FaultVerdict | None, str | None]:
    '''Run one incident through the compiled graph; return (verdict, error).'''
    state = graph.invoke(
        {'prompt': adjuster_prompt(incident_text), 'verdict': None, 'error': None}
    )
    return state['verdict'], state['error']
