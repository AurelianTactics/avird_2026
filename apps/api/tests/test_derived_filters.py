"""Tests for the structured filter + allow-list validation (U1).

The allow-list is the security boundary (plan KTD 3): only known values
survive, raw candidates never become identifiers. The known-value sets here
stand in for `IncidentData.fetch_known_values()`.
"""

from __future__ import annotations

from app.derived.filters import DerivedFilter, resolve

KNOWN_ENTITIES = ["Waymo", "Cruise", "Mercedes Benz", "Zoox"]
KNOWN_STATES = ["AZ", "CA", "TX", "NY"]


def _resolve(raw):
    return resolve(raw, known_entities=KNOWN_ENTITIES, known_states=KNOWN_STATES)


def test_entity_resolves_case_insensitively():
    res = _resolve({"entity": "waymo"})
    assert res.filter.entity == "Waymo"
    assert res.resolved == {"entity": "Waymo"}
    assert res.dropped == []


def test_entity_resolves_by_containment():
    res = _resolve({"entity": "merc"})
    assert res.filter.entity == "Mercedes Benz"


def test_state_name_and_code_resolve_to_same_code():
    by_name = _resolve({"state": "Arizona"})
    by_code = _resolve({"state": "AZ"})
    assert by_name.filter.state == "AZ"
    assert by_code.filter.state == "AZ"


def test_state_lowercase_code_resolves():
    res = _resolve({"state": "az"})
    assert res.filter.state == "AZ"


def test_severity_label_resolves():
    res = _resolve({"severity": "serious"})
    assert res.filter.severity_bucket == "Serious"


def test_unmapped_severity_drops_dimension():
    res = _resolve({"severity": "catastrophic mayhem"})
    assert res.filter.severity_bucket is None
    assert "severity" in res.dropped


def test_unknown_entity_dropped_no_constraint():
    res = _resolve({"entity": "Foobar"})
    assert res.filter.entity is None
    assert res.filter.is_empty()
    assert res.dropped == ["entity"]


def test_empty_input_yields_empty_filter_no_error():
    assert _resolve({}).filter.is_empty()
    assert _resolve(None).filter.is_empty()
    assert _resolve({"entity": "  ", "state": "", "severity": None}).filter.is_empty()


def test_sql_metacharacters_never_resolve_to_identifier():
    res = _resolve({"entity": "Waymo'; DROP TABLE"})
    # Must fail the known-value match — not be surfaced as "Waymo".
    assert res.filter.entity is None
    assert res.dropped == ["entity"]


def test_mixed_input_keeps_resolvable_drops_rest():
    res = _resolve({"entity": "Waymo", "state": "Atlantis"})
    assert res.filter.entity == "Waymo"
    assert res.filter.state is None
    assert res.resolved == {"entity": "Waymo"}
    assert res.dropped == ["state"]


def test_as_dict_includes_only_resolved_dimensions():
    res = _resolve({"entity": "Waymo", "state": "CA", "severity": "minor"})
    assert res.filter.as_dict() == {
        "entity": "Waymo",
        "state": "CA",
        "severity": "Minor",
    }


def test_all_three_dimensions_resolve():
    res = _resolve({"entity": "cruise", "state": "Texas", "severity": "Fatality"})
    assert res.filter == DerivedFilter(entity="Cruise", state="TX", severity_bucket="Fatality")
