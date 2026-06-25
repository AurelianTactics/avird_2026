'''Tests for schema_model.py — YAML round-trip, validation, draft refusal.'''
import pytest
import yaml
from pydantic import ValidationError

from schema_model import (
    NodeType,
    OntologySchema,
    PropertySpec,
    RelationshipType,
    dump_schema,
    load_frozen_schema,
    load_schema,
)


def tiny_schema():
    return OntologySchema(
        version='v001',
        node_types=[
            NodeType(label='Incident', provenance='column',
                     properties=[PropertySpec(name='incident_key', required=True)]),
            NodeType(label='Vehicle', provenance='column'),
            NodeType(label='Pedestrian', provenance='narrative'),
        ],
        relationship_types=[
            RelationshipType(label='INVOLVES', provenance='column'),
        ],
        patterns=[('Incident', 'INVOLVES', 'Vehicle')],
        competency_questions=['Which company has the most incidents?'],
    )


def test_yaml_round_trip_is_lossless(tmp_path):
    path = tmp_path / 's.yaml'
    original = tiny_schema()
    dump_schema(original, path)
    reloaded = load_schema(path)
    assert reloaded == original
    # and a second trip through disk is byte-identical
    path2 = tmp_path / 's2.yaml'
    dump_schema(reloaded, path2)
    assert path.read_text(encoding='utf-8') == path2.read_text(encoding='utf-8')


def test_misspelled_key_rejected():
    data = tiny_schema().model_dump(mode='json')
    data['node_typos'] = data.pop('node_types')
    with pytest.raises(ValidationError, match='node_typos'):
        OntologySchema.model_validate(data)


def test_pattern_with_undeclared_node_type_rejected():
    data = tiny_schema().model_dump(mode='json')
    data['patterns'].append(['Incident', 'INVOLVES', 'Ghost'])
    with pytest.raises(ValidationError, match='Ghost'):
        OntologySchema.model_validate(data)


def test_pattern_with_undeclared_relationship_rejected():
    data = tiny_schema().model_dump(mode='json')
    data['patterns'].append(['Incident', 'HAUNTS', 'Vehicle'])
    with pytest.raises(ValidationError, match='HAUNTS'):
        OntologySchema.model_validate(data)


def test_duplicate_node_label_rejected():
    data = tiny_schema().model_dump(mode='json')
    data['node_types'].append(data['node_types'][0])
    with pytest.raises(ValidationError, match='duplicate'):
        OntologySchema.model_validate(data)


def test_unquoted_no_scalar_surfaces_as_type_error(tmp_path):
    # The YAML-1.1 Norway problem: a bare `no` parses as boolean False and
    # must fail string validation rather than silently becoming "False".
    path = tmp_path / 'norway.yaml'
    path.write_text(
        'version: v001\n'
        'node_types:\n'
        '  - label: no\n'
        '    provenance: column\n'
        'relationship_types: []\n'
        'patterns: []\n',
        encoding='utf-8',
    )
    with pytest.raises(ValidationError):
        load_schema(path)


def test_dump_quotes_ambiguous_scalars(tmp_path):
    schema = OntologySchema(
        version='v001',
        node_types=[NodeType(label='no', provenance='column')],
    )
    path = dump_schema(schema, tmp_path / 'amb.yaml')
    assert load_schema(path).node_types[0].label == 'no'


def test_empty_yaml_raises_clear_error(tmp_path):
    path = tmp_path / 'empty.yaml'
    path.write_text('', encoding='utf-8')
    with pytest.raises(ValueError, match='empty'):
        load_schema(path)


def test_invalid_provenance_rejected():
    with pytest.raises(ValidationError):
        NodeType(label='X', provenance='vibes')


def test_label_charset_enforced_at_schema_load():
    # Labels are interpolated into Cypher DDL; a hand-edited label with a
    # space must fail at schema load, before extraction money is spent.
    for bad in ('Traffic Control', '1stParty', 'has-part', 'back`tick'):
        with pytest.raises(ValidationError, match='label'):
            NodeType(label=bad, provenance='column')
        with pytest.raises(ValidationError, match='label'):
            RelationshipType(label=bad, provenance='narrative')
    assert NodeType(label='TrafficControl', provenance='column').label
    assert RelationshipType(label='HAS_PART', provenance='narrative').label


def test_load_frozen_schema_rejects_drafts_path(tmp_path):
    drafts = tmp_path / 'schema' / 'drafts'
    drafts.mkdir(parents=True)
    path = dump_schema(tiny_schema(), drafts / 'v001-draft.yaml')
    with pytest.raises(ValueError, match='draft'):
        load_frozen_schema(path)
    # the same content outside drafts/ loads fine
    frozen = dump_schema(tiny_schema(), tmp_path / 'schema' / 'v001.yaml')
    assert load_frozen_schema(frozen).version == 'v001'


def test_yaml_lists_validate_to_pattern_tuples(tmp_path):
    path = dump_schema(tiny_schema(), tmp_path / 's.yaml')
    raw = yaml.safe_load(path.read_text(encoding='utf-8'))
    assert isinstance(raw['patterns'][0], list)
    assert load_schema(path).patterns[0] == ('Incident', 'INVOLVES', 'Vehicle')
