"""Tests for the deterministic derived routes (U3).

Route tests override `get_incident_data` with an in-memory fake (no live
Postgres), exactly like `test_groupings.py`. The fake mimics the data layer:
`fetch_known_values` supplies the allow-list vocabulary and `fetch_derived_rows`
applies entity/state filtering over canned rows so the route's resolve ->
fetch -> aggregate wiring is exercised end to end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.derived.routes import get_filter_model, get_incident_data
from app.main import app


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _contact_row(entity, sv, cp, state=None, severity=None, narrative=None):
    row = {
        "master_entity": entity,
        "State Clean": state,
        "Highest Injury Severity Alleged": severity,
        "Narrative": narrative,
        "SV Pre-Crash Movement": "Going Straight",
        "CP Pre-Crash Movement": "Stopped",
    }
    for area in sv:
        row[f"SV Contact Area - {area}"] = "Y"
    for area in cp:
        row[f"CP Contact Area - {area}"] = "Y"
    return row


ROWS = [
    _contact_row("Waymo", ["Front"], ["Rear"], state="AZ", severity="Fatality", narrative="clean"),
    _contact_row(
        "Waymo", ["Left"], ["Right"], state="CA", severity="Minor", narrative="[REDACTED]"
    ),
    _contact_row("Cruise", ["Front"], ["Front"], state="AZ", severity="Minor", narrative="see CBI"),
]


class FakeData:
    def __init__(self, rows):
        self._rows = rows

    async def fetch_known_values(self):
        return {
            "entities": sorted({r["master_entity"] for r in self._rows}),
            "states": sorted({r["State Clean"] for r in self._rows if r["State Clean"]}),
        }

    async def fetch_derived_rows(self, filt):
        rows = self._rows
        if filt.entity is not None:
            rows = [r for r in rows if r["master_entity"] == filt.entity]
        if filt.state is not None:
            rows = [r for r in rows if r["State Clean"] == filt.state]
        return rows


def _use(rows):
    app.dependency_overrides[get_incident_data] = lambda: FakeData(rows)


def _cell(matrix, sv, cp):
    for c in matrix["cells"]:
        if c["sv"] == sv and c["cp"] == cp:
            return c["count"]
    return 0


def _get(path):
    with TestClient(app) as client:
        return client.get(path)


# --- /derived/heatmaps ------------------------------------------------------


def test_heatmaps_no_params_aggregates_all_rows():
    _use(ROWS)
    body = _get("/derived/heatmaps").json()
    assert set(body) == {"contact_areas", "pre_crash", "applied_filter"}
    assert body["applied_filter"] == {}
    # All three rows feed the contact-area matrix.
    assert _cell(body["contact_areas"], "Front", "Rear") == 1
    assert _cell(body["contact_areas"], "Front", "Front") == 1


def test_heatmaps_entity_and_state_filter():
    _use(ROWS)
    body = _get("/derived/heatmaps?entity=Waymo&state=AZ").json()
    assert body["applied_filter"] == {"entity": "Waymo", "state": "AZ"}
    # Only the Waymo/AZ row (Front->Rear) survives.
    assert _cell(body["contact_areas"], "Front", "Rear") == 1
    assert _cell(body["contact_areas"], "Front", "Front") == 0


def test_heatmaps_unknown_entity_treated_as_unfiltered():
    _use(ROWS)
    resp = _get("/derived/heatmaps?entity=Foobar")
    assert resp.status_code == 200
    body = resp.json()
    # Unknown dimension dropped -> not present in applied_filter.
    assert "entity" not in body["applied_filter"]


def test_heatmaps_severity_filter_applied_post_fetch():
    _use(ROWS)
    body = _get("/derived/heatmaps?severity=Fatality").json()
    assert body["applied_filter"] == {"severity": "Fatality"}
    # Only the Fatality row (Front->Rear) remains.
    assert _cell(body["contact_areas"], "Front", "Rear") == 1
    assert _cell(body["contact_areas"], "Left", "Right") == 0


def test_heatmaps_response_shape():
    _use(ROWS)
    body = _get("/derived/heatmaps").json()
    for key in ("contact_areas", "pre_crash"):
        assert set(body[key]) == {"sv_axis", "cp_axis", "cells"}


# --- /derived/redaction -----------------------------------------------------


def test_redaction_per_entity_over_all_rows():
    _use(ROWS)
    body = _get("/derived/redaction").json()
    out = {r["entity"]: r for r in body["redaction"]}
    assert out["Waymo"]["redacted"] == 1
    assert out["Waymo"]["total"] == 2
    assert out["Cruise"]["redacted"] == 1
    assert out["Cruise"]["total"] == 1


def test_redaction_ignores_query_params():
    _use(ROWS)
    filtered = _get("/derived/redaction?entity=Waymo").json()
    unfiltered = _get("/derived/redaction").json()
    assert filtered == unfiltered


# --- POST /derived/query (U6) -----------------------------------------------


class FakeModel:
    def __init__(self, *, returns=None, raises=False):
        self._returns = returns
        self._raises = raises

    def propose(self, text):
        if self._raises:
            raise RuntimeError("LLM down")
        return self._returns


def _use_model(model):
    app.dependency_overrides[get_filter_model] = lambda: model


def _post(path, json):
    with TestClient(app) as client:
        return client.post(path, json=json)


def test_query_happy_path_filtered():
    _use(ROWS)
    _use_model(FakeModel(returns='{"entity": "Waymo", "state": "AZ"}'))
    resp = _post("/derived/query", {"text": "only Waymo in Arizona"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["applied_filter"] == {"entity": "Waymo", "state": "AZ"}
    assert body["fallback"] is False
    assert _cell(body["contact_areas"], "Front", "Rear") == 1


def test_query_empty_text_default_no_filter():
    _use(ROWS)
    _use_model(FakeModel(returns="{}"))
    body = _post("/derived/query", {"text": ""}).json()
    assert body["fallback"] is False
    assert body["applied_filter"] == {}


def test_query_agent_failure_never_500s():
    _use(ROWS)
    _use_model(FakeModel(raises=True))
    # Unrecoverable text (no known value) -> default view, still 200 not 500.
    resp = _post("/derived/query", {"text": "asdf qwer zxcv"})
    assert resp.status_code == 200  # not 500
    body = resp.json()
    assert body["fallback"] is True
    assert body["applied_filter"] == {}


def test_query_recovers_without_llm():
    # LLM raises, but the text names known values -> deterministic recovery
    # filters anyway (the keyless / "maybe filter by that" path).
    _use(ROWS)
    _use_model(FakeModel(raises=True))
    body = _post("/derived/query", {"text": "only Waymo in Arizona"}).json()
    assert body["fallback"] is False
    assert body["applied_filter"] == {"entity": "Waymo", "state": "AZ"}
    assert _cell(body["contact_areas"], "Front", "Rear") == 1


def test_query_response_shape_matches_heatmaps_plus_agent_meta():
    _use(ROWS)
    _use_model(FakeModel(returns='{"entity": "Waymo"}'))
    body = _post("/derived/query", {"text": "waymo"}).json()
    assert set(body) >= {
        "contact_areas",
        "pre_crash",
        "applied_filter",
        "fallback",
        "message",
    }


def test_query_over_length_text_rejected_before_agent():
    _use(ROWS)
    # A model that raises if invoked proves rejection happens before the agent.
    _use_model(FakeModel(raises=True))
    resp = _post("/derived/query", {"text": "x" * 501})
    assert resp.status_code == 422


def test_derived_router_is_read_only():
    # Only GET (and the later POST /query) — no mutation verbs registered.
    methods = {(route.path, m) for route in app.routes for m in getattr(route, "methods", set())}
    mutating = {
        (p, m) for (p, m) in methods if p.startswith("/derived") and m in {"PUT", "PATCH", "DELETE"}
    }
    assert mutating == set()
