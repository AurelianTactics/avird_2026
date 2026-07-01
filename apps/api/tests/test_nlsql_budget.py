"""Tests for the nlsql budget guard (P1 web delivery).

Mirrors the derived budget guard's semantics but pins the KTD-5 fix: the estimate
is sized to the larger text-to-SQL prompt, not the small NL-filter one.
"""

from __future__ import annotations

from app.derived.budget import _ESTIMATE_INPUT_CHARS as DERIVED_INPUT_CHARS
from app.nlsql.budget import _ESTIMATE_INPUT_CHARS, InMemoryBudgetGuard


async def test_estimate_is_larger_than_the_nl_filter_estimate():
    # KTD-5: the P1 prompt is bigger, so its per-call reservation must be bigger.
    assert _ESTIMATE_INPUT_CHARS > DERIVED_INPUT_CHARS
    guard = InMemoryBudgetGuard(daily_limit_usd=100.0)
    assert guard.estimate_cost() > 0


async def test_reserve_then_release_frees_budget():
    guard = InMemoryBudgetGuard(daily_limit_usd=100.0)
    r = await guard.reserve(guard.estimate_cost())
    assert r is not None
    assert guard.spent() > 0
    await guard.release(r)
    assert guard.spent() == 0.0


async def test_over_cap_reserve_returns_none():
    guard = InMemoryBudgetGuard(daily_limit_usd=0.0)
    assert await guard.reserve(guard.estimate_cost()) is None
