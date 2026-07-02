"""Tests for the graph card built from the frozen ontology schema (P3, U14).

The card and the allow-lists come from one parse, so the fixture dict below is
shared with the validator tests (same vocabulary) — the plan's "integration:
the produced allow-list is exactly what the validator consumes" scenario.
Loading the real committed yaml is also pinned: it's the production path and
the file is frozen, so this is cheap and can't flake.
"""

from __future__ import annotations

from app.kgquery.graph_card import SCHEMA_PATH, load_graph_card, parse_graph_card

SCHEMA_DICT = {
    "version": "v001-test",
    "node_types": [
        {
            "label": "Incident",
            "description": "One crash incident.",
            "properties": [
                {"name": "incident_key", "type": "STRING", "required": True},
                {"name": "highest_injury_severity", "type": "STRING"},
            ],
        },
        {"label": "Vehicle", "description": "A vehicle.", "properties": []},
        {"label": "Company", "description": "An operator/reporter.", "properties": []},
        {"label": "Pedestrian", "description": "A pedestrian.", "properties": []},
    ],
    "relationship_types": [
        {"label": "INVOLVES", "description": "Incident involves a vehicle."},
        {"label": "OPERATED_BY", "description": "Vehicle operated by company."},
        {"label": "CONTACTED", "description": "Contact between participants."},
    ],
    "patterns": [
        ["Incident", "INVOLVES", "Vehicle"],
        ["Vehicle", "OPERATED_BY", "Company"],
        ["Vehicle", "CONTACTED", "Pedestrian"],
    ],
}


def make_card():
    return parse_graph_card(SCHEMA_DICT)


def test_card_lists_every_label_rel_and_pattern():
    card = make_card()
    text = card.render()
    for label in ("Incident", "Vehicle", "Company", "Pedestrian"):
        assert label in text
    for rel in ("INVOLVES", "OPERATED_BY", "CONTACTED"):
        assert rel in text
    assert "(Incident)-[:INVOLVES]->(Vehicle)" in text
    # Properties render with their types; the universal key/name note is present.
    assert "incident_key (STRING)" in text
    assert "`key`" in text and "`name`" in text


def test_allow_lists_match_the_schema_exactly():
    card = make_card()
    assert card.allowed_labels == {"Incident", "Vehicle", "Company", "Pedestrian"}
    assert card.allowed_relationships == {"INVOLVES", "OPERATED_BY", "CONTACTED"}


def test_real_committed_schema_loads_and_memoizes():
    card = load_graph_card()
    assert card is load_graph_card()  # module-level memo
    # The frozen v001 vocabulary the whole phase is built on.
    assert "Incident" in card.allowed_labels
    assert "INVOLVES" in card.allowed_relationships
    assert len(card.patterns) > 50
    assert SCHEMA_PATH.name == "v001.yaml"


def test_missing_schema_file_raises_setup_hint(tmp_path):
    import pytest

    with pytest.raises(RuntimeError, match="ontology schema not found"):
        load_graph_card(tmp_path / "nope.yaml")
