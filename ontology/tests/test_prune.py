'''Tests for prune.py — quote verification, label/pattern pruning, keys.'''
from dataclasses import dataclass, field

from prune import (
    EntityKeyer,
    normalize_for_quote,
    prune_extraction,
    verify_quote,
)
from schema_model import NodeType, RelationshipType
from seed_schema import build_seed_schema

TEXT = ('The Waymo AV was proceeding through the intersection when a '
        'pedestrian entered the roadway. The AV braked, but made contact '
        'with the pedestrian at low speed.')


@dataclass
class RawEntity:
    type: str
    name: str
    supporting_quote: str
    properties: dict = field(default_factory=dict)


@dataclass
class RawRelationship:
    type: str
    source_type: str
    source_name: str
    target_type: str
    target_name: str
    supporting_quote: str


@dataclass
class Raw:
    entities: list = field(default_factory=list)
    relationships: list = field(default_factory=list)


def narrative_schema():
    '''Seed schema + the narrative types these tests exercise.'''
    seed = build_seed_schema()
    return seed.model_copy(update={
        'node_types': seed.node_types + [
            NodeType(label='Pedestrian', provenance='narrative'),
        ],
        'relationship_types': seed.relationship_types + [
            RelationshipType(label='STRUCK', provenance='narrative'),
        ],
        'patterns': seed.patterns + [('Vehicle', 'STRUCK', 'Pedestrian')],
    })


def prune(raw, text=TEXT):
    return prune_extraction(narrative_schema(), raw, text, 'INC-1')


# ---------------------------------------------------------------------------
# Quote verification
# ---------------------------------------------------------------------------
def test_quote_accepted_after_case_whitespace_punctuation_normalization():
    quote = 'a PEDESTRIAN,  entered the roadway!'
    assert verify_quote(quote, TEXT) == 'ok'


def test_quote_with_no_plausible_span_is_hallucination():
    assert verify_quote('the drone landed on the rooftop', TEXT) == 'hallucination'
    assert verify_quote('', TEXT) == 'hallucination'


def test_near_miss_quote_is_quote_mismatch_not_hallucination():
    # Mostly-matching span with a tail the narrative never says.
    quote = 'a pedestrian entered the roadway suddenly'
    assert verify_quote(quote, TEXT) == 'quote_mismatch'


def test_normalize_for_quote_is_deterministic():
    s = 'The AV  braked, but...'
    assert normalize_for_quote(s) == normalize_for_quote(s)
    assert normalize_for_quote(s) == 'the av braked but'


# ---------------------------------------------------------------------------
# Entity pruning
# ---------------------------------------------------------------------------
def test_valid_entity_survives_with_key_and_narrative_provenance():
    raw = Raw(entities=[RawEntity('Pedestrian', 'pedestrian',
                                  'a pedestrian entered the roadway')])
    result = prune(raw)
    [ent] = result.entities
    assert ent.key == 'INC-1:Pedestrian:1'
    assert ent.provenance == 'narrative'
    assert result.counters['hallucination'] == 0


def test_hallucinated_entity_dropped_and_counted():
    raw = Raw(entities=[RawEntity('Pedestrian', 'pedestrian',
                                  'a cyclist swerved into traffic')])
    result = prune(raw)
    assert result.entities == []
    assert result.counters['hallucination'] == 1
    assert any('hallucination' in d for d in result.dropped)


def test_near_miss_counts_as_quote_mismatch_not_hallucination():
    raw = Raw(entities=[RawEntity('Pedestrian', 'pedestrian',
                                  'a pedestrian entered the roadway suddenly')])
    result = prune(raw)
    assert result.entities == []
    assert result.counters['quote_mismatch'] == 1
    assert result.counters['hallucination'] == 0


def test_unknown_entity_label_dropped_and_logged():
    raw = Raw(entities=[RawEntity('Dinosaur', 'rex',
                                  'a pedestrian entered the roadway')])
    result = prune(raw)
    assert result.entities == []
    assert result.counters['unknown_entity_label'] == 1


def test_duplicate_mentions_collapse_to_one_keyed_entity():
    raw = Raw(entities=[
        RawEntity('Pedestrian', 'Pedestrian',
                  'a pedestrian entered the roadway', {'age': 'adult'}),
        RawEntity('Pedestrian', 'pedestrian',
                  'contact with the pedestrian', {'injured': 'yes'}),
    ])
    result = prune(raw)
    [ent] = result.entities
    assert result.counters['duplicate_collapsed'] == 1
    assert ent.properties == {'age': 'adult', 'injured': 'yes'}


# ---------------------------------------------------------------------------
# Relationship pruning
# ---------------------------------------------------------------------------
def two_party_raw(rel_type='STRUCK', source=('Vehicle', 'the AV'),
                  target=('Pedestrian', 'pedestrian')):
    return Raw(
        entities=[
            RawEntity('Vehicle', 'the AV', 'The AV braked'),
            RawEntity('Pedestrian', 'pedestrian',
                      'a pedestrian entered the roadway'),
        ],
        relationships=[RawRelationship(
            rel_type, source[0], source[1], target[0], target[1],
            'made contact with the pedestrian')],
    )


def test_valid_relationship_survives():
    result = prune(two_party_raw())
    [rel] = result.relationships
    assert rel.type == 'STRUCK'
    assert rel.direction_corrected is False
    assert rel.as_emitted is None


def test_reversed_direction_corrected_and_as_emitted_persisted():
    raw = two_party_raw(source=('Pedestrian', 'pedestrian'),
                        target=('Vehicle', 'the AV'))
    result = prune(raw)
    [rel] = result.relationships
    assert rel.direction_corrected is True
    assert result.counters['direction_corrected'] == 1
    # corrected: Vehicle -> Pedestrian; as-emitted preserved for eval
    assert rel.source_key == 'INC-1:V1'
    assert rel.target_key == 'INC-1:Pedestrian:1'
    assert rel.as_emitted == {'source_key': 'INC-1:Pedestrian:1',
                              'target_key': 'INC-1:V1'}


def test_relationship_matching_no_pattern_either_way_dropped():
    raw = two_party_raw(rel_type='OPERATED_BY')  # Vehicle-OPERATED_BY->Pedestrian
    result = prune(raw)
    assert result.relationships == []
    assert result.counters['pattern_violation'] == 1


def test_unknown_relationship_label_dropped():
    raw = two_party_raw(rel_type='TELEPORTED')
    result = prune(raw)
    assert result.relationships == []
    assert result.counters['unknown_relationship_label'] == 1


def test_relationship_of_dropped_entity_is_dangling():
    raw = two_party_raw()
    raw.entities[1] = RawEntity('Pedestrian', 'pedestrian',
                                'completely invented quote about a llama')
    result = prune(raw)
    assert result.relationships == []
    assert result.counters['hallucination'] == 1
    assert result.counters['dangling_relationship'] == 1


def test_relationship_with_failed_quote_dropped():
    raw = two_party_raw()
    raw.relationships[0].supporting_quote = 'never said in the narrative at all'
    result = prune(raw)
    assert result.relationships == []
    assert result.counters['hallucination'] == 1


# ---------------------------------------------------------------------------
# Entity keys
# ---------------------------------------------------------------------------
def test_subject_vehicle_key_prefers_vin():
    keyer = EntityKeyer('INC-1')
    assert keyer.key_for('Vehicle', 'sv', is_subject=True, vin='VIN123') == 'VIN123'
    assert EntityKeyer('INC-1').key_for('Vehicle', 'sv', is_subject=True) == 'INC-1:SV'


def test_vinless_partner_vehicles_get_distinct_ordinals():
    keyer = EntityKeyer('INC-1')
    sv = keyer.key_for('Vehicle', 'sv', is_subject=True)
    v1 = keyer.key_for('Vehicle', 'a sedan')
    v2 = keyer.key_for('Vehicle', 'a pickup truck')
    assert sv == 'INC-1:SV'
    assert v1 == 'INC-1:V1'
    assert v2 == 'INC-1:V2'
    assert len({sv, v1, v2}) == 3
    # same normalized mention -> same key, not a new ordinal
    assert keyer.key_for('Vehicle', 'A Sedan') == v1


def test_company_and_condition_keys_are_shared_not_incident_scoped():
    a = EntityKeyer('INC-1')
    b = EntityKeyer('INC-2')
    assert a.key_for('Company', 'Waymo LLC') == b.key_for('Company', 'Waymo LLC')
    assert a.key_for('EnvironmentalCondition', 'Rain') == \
        b.key_for('EnvironmentalCondition', 'Rain')


def test_narrative_only_entities_scoped_per_incident():
    a = EntityKeyer('INC-1')
    b = EntityKeyer('INC-2')
    assert a.key_for('Pedestrian', 'pedestrian') == 'INC-1:Pedestrian:1'
    assert b.key_for('Pedestrian', 'pedestrian') == 'INC-2:Pedestrian:1'
    assert a.key_for('Pedestrian', 'second pedestrian') == 'INC-1:Pedestrian:2'
