'''Tests for seed_schema.py — deterministic generation, column verification.'''
import json

import pytest

from seed_schema import COLUMN_DICTIONARY, build_seed_schema
from schema_model import OntologySchema


def test_seed_builds_and_validates_against_real_dictionary():
    schema = build_seed_schema()
    assert isinstance(schema, OntologySchema)
    labels = {n.label for n in schema.node_types}
    assert {'Incident', 'Vehicle', 'Company', 'Location'} <= labels
    assert all(n.provenance == 'column' for n in schema.node_types)
    assert all(r.provenance == 'column' for r in schema.relationship_types)
    assert schema.patterns  # pattern validity enforced by the model itself


def test_seed_is_deterministic():
    assert build_seed_schema() == build_seed_schema()


def test_unknown_source_column_fails_loudly(tmp_path):
    data = json.loads(COLUMN_DICTIONARY.read_text(encoding='utf-8'))
    data['columns'] = [c for c in data['columns'] if c['name'] != 'VIN']
    trimmed = tmp_path / 'column_dictionary.json'
    trimmed.write_text(json.dumps(data), encoding='utf-8')
    with pytest.raises(ValueError, match='VIN'):
        build_seed_schema(dictionary_path=trimmed)


def test_every_property_names_its_source_columns():
    schema = build_seed_schema()
    for node in schema.node_types:
        for prop in node.properties:
            assert prop.description.startswith('source: '), (node.label, prop.name)
