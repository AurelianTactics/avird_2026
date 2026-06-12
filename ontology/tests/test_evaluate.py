'''Tests for evaluate.py — toy fixtures with hand-computed exact metrics.'''
import json

import pytest

from evaluate import (
    approval_diff,
    evaluate_consolidation,
    evaluate_extraction,
    evaluate_competency_questions,
    fuzzy_overlap,
    golden_split_path,
    graph_assertion_queries,
    run_graph_assertions,
    write_summary,
)
from test_prune import narrative_schema


def ent(key, etype, name, quote, provenance='narrative', **extra):
    return {'key': key, 'type': etype, 'name': name, 'quote': quote,
            'provenance': provenance, 'properties': {}, **extra}


def rel(rtype, source_key, target_key, provenance='narrative', **extra):
    return {'type': rtype, 'source_key': source_key, 'target_key': target_key,
            'provenance': provenance, 'quote': '', **extra}


def toy_golden():
    return [{
        'doc_key': 'INC-1', 'split': 'dev', 'guidelines_version': 'v0.1',
        'text_sha256': 'h',
        'entities': [
            # column entity must be excluded from scoring entirely
            ent('INC-1', 'Incident', 'INC-1', '', provenance='column'),
            ent('INC-1:V1', 'Vehicle', 'the AV', 'The AV braked'),
            ent('INC-1:Pedestrian:1', 'Pedestrian', 'pedestrian',
                'a pedestrian entered the roadway'),
            ent('INC-1:Cyclist:1', 'Cyclist', 'cyclist', 'a cyclist swerved'),
            ent('INC-1:UNMAPPED:1', 'UNMAPPED', 'fire crew', 'fire crew',
                candidate_type='EmergencyResponder'),
        ],
        'relationships': [
            rel('INVOLVES', 'INC-1', 'INC-1:V1', provenance='column'),
            rel('STRUCK', 'INC-1:V1', 'INC-1:Pedestrian:1'),
        ],
    }]


def toy_artifact():
    return [{
        'doc_key': 'INC-1', 'status': 'ok',
        'counters': {'hallucination': 2, 'quote_mismatch': 1},
        'entities': [
            ent('INC-1', 'Incident', 'INC-1', '', provenance='column'),
            # strict + relaxed match for the Vehicle (exact name)
            ent('INC-1:V1', 'Vehicle', 'the AV', 'The AV braked'),
            # relaxed-only match for the Pedestrian (name superset, sub-quote)
            ent('INC-1:Pedestrian:1', 'Pedestrian', 'the pedestrian',
                'pedestrian entered the roadway'),
            # false positive in both modes
            ent('INC-1:Pedestrian:2', 'Pedestrian', 'a jogger',
                'unrelatedquote zzz'),
        ],
        'relationships': [
            rel('STRUCK', 'INC-1:V1', 'INC-1:Pedestrian:1'),
            rel('STRUCK', 'INC-1:V1', 'INC-1:Pedestrian:2',
                direction_corrected=True,
                as_emitted={'source_key': 'INC-1:Pedestrian:2',
                            'target_key': 'INC-1:V1'}),
        ],
    }]


def test_extraction_exact_prf_strict_and_relaxed():
    metrics = evaluate_extraction(toy_golden(), toy_artifact())
    # gold mappable narrative entities: Vehicle, Pedestrian, Cyclist (3)
    # preds narrative: Vehicle(strict tp), Pedestrian(relaxed-only), jogger(fp)
    strict = metrics['entities']['strict']
    assert (strict['tp'], strict['fp'], strict['fn']) == (1, 2, 2)
    assert strict['precision'] == pytest.approx(0.3333, abs=1e-4)
    assert strict['f1'] == pytest.approx(0.3333, abs=1e-4)
    relaxed = metrics['entities']['relaxed']
    assert (relaxed['tp'], relaxed['fp'], relaxed['fn']) == (2, 1, 1)
    assert relaxed['f1'] == pytest.approx(0.6667, abs=1e-4)


def test_extraction_relationship_prf_rides_entity_matching():
    metrics = evaluate_extraction(toy_golden(), toy_artifact())
    strict = metrics['relationships']['strict']
    # pedestrian unmatched strictly -> the golden STRUCK can't match
    assert (strict['tp'], strict['fp'], strict['fn']) == (0, 2, 1)
    relaxed = metrics['relationships']['relaxed']
    assert (relaxed['tp'], relaxed['fp'], relaxed['fn']) == (1, 1, 0)
    assert relaxed['precision'] == 0.5
    assert relaxed['recall'] == 1.0


def test_column_provenance_excluded_from_scoring():
    golden, artifact = toy_golden(), toy_artifact()
    # add more column instances on both sides; numbers must not move
    baseline = evaluate_extraction(golden, artifact)
    golden[0]['entities'].append(
        ent('waymo', 'Company', 'waymo', '', provenance='column'))
    artifact[0]['entities'].append(
        ent('waymo', 'Company', 'waymo', '', provenance='column'))
    artifact[0]['relationships'].append(
        rel('REPORTED_BY', 'INC-1', 'waymo', provenance='column'))
    assert evaluate_extraction(golden, artifact) == baseline


def test_rates_match_fixture_construction():
    rates = evaluate_extraction(toy_golden(), toy_artifact())['rates']
    assert rates['hallucination_count'] == 2
    assert rates['quote_mismatch_count'] == 1
    # attempted = 3 narrative ents + 2 narrative rels + 2 halluc + 1 mismatch
    assert rates['hallucination_rate'] == pytest.approx(2 / 8)
    assert rates['quote_mismatch_rate'] == pytest.approx(1 / 8)
    assert rates['direction_error_rate'] == 0.5     # 1 of 2 pred rels
    assert rates['omission_strict'] == 2
    assert rates['omission_relaxed'] == 1


def test_component_breakdown_localizes_failures():
    components = evaluate_extraction(toy_golden(), toy_artifact())['components']
    # detection (type-agnostic): Vehicle + Pedestrian found, Cyclist missed
    assert components['detection_recall'] == pytest.approx(0.6667, abs=1e-4)
    assert components['typing_accuracy'] == 1.0


def test_coverage_counts_unmapped_in_denominator():
    coverage = evaluate_extraction(toy_golden(), toy_artifact())['coverage']
    assert coverage == {'mapped': 3, 'unmapped': 1, 'coverage': 0.75}


def test_artifact_missing_golden_doc_raises():
    with pytest.raises(ValueError, match='include-golden'):
        evaluate_extraction(toy_golden(), [])


def test_golden_relationship_anchored_at_column_key_can_match():
    # Guidelines allow golden relationships at the subject vehicle's column
    # key (e.g. COLLIDED_WITH); those endpoints map by identity, not via
    # narrative-entity matching.
    golden = [{
        'doc_key': 'INC-2', 'split': 'dev', 'guidelines_version': 'v0.1',
        'text_sha256': 'h',
        'entities': [
            ent('VIN9', 'Vehicle', 'subject vehicle', '', provenance='column'),
            ent('INC-2:Pedestrian:1', 'Pedestrian', 'pedestrian',
                'struck a pedestrian'),
        ],
        'relationships': [rel('STRUCK', 'VIN9', 'INC-2:Pedestrian:1')],
    }]
    artifact = [{
        'doc_key': 'INC-2', 'status': 'ok', 'counters': {},
        'entities': [
            ent('VIN9', 'Vehicle', 'subject vehicle', '', provenance='column'),
            ent('INC-2:Pedestrian:1', 'Pedestrian', 'pedestrian',
                'struck a pedestrian'),
        ],
        'relationships': [rel('STRUCK', 'VIN9', 'INC-2:Pedestrian:1')],
    }]
    metrics = evaluate_extraction(golden, artifact)
    assert metrics['relationships']['strict']['tp'] == 1
    assert metrics['relationships']['strict']['fn'] == 0


# ---------------------------------------------------------------------------
# Consolidation (R16)
# ---------------------------------------------------------------------------
def test_consolidation_pairwise_exact_numbers():
    proposed = [
        {'kind': 'node', 'canonical_name': 'Pedestrian',
         'members': ['Pedestrian', 'Person On Foot']},          # pair (a,b)
        {'kind': 'node', 'canonical_name': 'Animal',
         'members': ['Animal', 'Deer']},                        # pair (c,d)
    ]
    golden = [
        {'kind': 'node', 'canonical_name': 'Pedestrian',
         'members': ['Pedestrian', 'Person On Foot', 'Walker']},
        # gold pairs: (a,b), (a,w), (b,w)
    ]
    metrics = evaluate_consolidation(proposed, golden)
    assert (metrics['pairwise']['tp'], metrics['pairwise']['fp'],
            metrics['pairwise']['fn']) == (1, 1, 2)
    assert metrics['pairwise']['precision'] == 0.5
    assert metrics['pairwise']['recall'] == pytest.approx(0.3333, abs=1e-4)
    assert metrics['pairwise']['f1'] == 0.4


def test_consolidation_kind_segregates_pairs():
    proposed = [{'kind': 'node', 'canonical_name': 'X', 'members': ['A', 'B']}]
    golden = [{'kind': 'relationship', 'canonical_name': 'X',
               'members': ['A', 'B']}]
    metrics = evaluate_consolidation(proposed, golden)
    assert metrics['pairwise']['tp'] == 0


def test_approval_diff():
    draft = narrative_schema()
    from schema_model import NodeType
    approved = draft.model_copy(update={
        'node_types': [n for n in draft.node_types if n.label != 'Pedestrian']
                      + [NodeType(label='Cyclist', provenance='narrative')],
    })
    diff = approval_diff(draft, approved)
    assert diff['node_types'] == {'added': ['Cyclist'],
                                  'dropped': ['Pedestrian']}


# ---------------------------------------------------------------------------
# Held-out hygiene (AE4)
# ---------------------------------------------------------------------------
def test_heldout_refused_without_flag():
    with pytest.raises(PermissionError, match='heldout'):
        golden_split_path('heldout')
    assert golden_split_path('heldout', allow_heldout=True).name == 'heldout.jsonl'
    assert golden_split_path('dev').name == 'dev.jsonl'


# ---------------------------------------------------------------------------
# Graph assertions
# ---------------------------------------------------------------------------
def test_assertion_builder_emits_expected_queries():
    queries = dict(graph_assertion_queries(narrative_schema()))
    assert 'orphan_nodes' in queries
    assert 'NOT (n)--()' in queries['orphan_nodes']
    assert 'incident_without_vehicle' in queries
    # required props from the seed: Incident.incident_key etc.
    assert 'missing_required_Incident_incident_key' in queries
    assert 'IS NULL' in queries['missing_required_Incident_incident_key']


def test_run_graph_assertions_with_stub_driver(stub_driver_factory):
    driver = stub_driver_factory(results={
        'NOT (n)--()': [{'n': 1}],
        'MATCH ()-[r]->()': [{'n': 5}],
        'db.labels': [{'labels': ['Incident', 'Vehicle', 'Mystery']}],
        'IS NULL': [{'n': 0}],
        'INVOLVES': [{'n': 0}],
        'MATCH (n) RETURN count(n)': [{'n': 10}],
    })
    results = run_graph_assertions(driver, narrative_schema())
    assert results['node_count'] == 10
    assert results['orphan_rate'] == 0.1
    assert results['undeclared_labels'] == ['Mystery']
    assert results['incident_without_vehicle'] == 0


def test_competency_question_answerability(stub_driver_factory):
    schema = narrative_schema().model_copy(update={
        'competency_questions': ['Which company has most incidents?',
                                 'How many pedestrian strikes?'],
    })
    driver = stub_driver_factory(results={'MATCH (c:Company)': [{'x': 1}]})
    metrics = evaluate_competency_questions(driver, schema, {
        'Which company has most incidents?':
            'MATCH (c:Company) RETURN c LIMIT 1',
    })
    assert metrics['total'] == 2
    assert metrics['answerable'] == 1
    assert metrics['answerability'] == 0.5
    assert metrics['questions'][1]['has_query'] is False


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def test_summary_deterministic_for_fixed_inputs(tmp_path):
    metrics = evaluate_extraction(toy_golden(), toy_artifact())
    j1, m1 = write_summary(metrics, 'eval-test', out_dir=tmp_path,
                           inputs={'artifact': 'a.jsonl'})
    first_json = j1.read_bytes()
    first_md = m1.read_bytes()
    j2, m2 = write_summary(metrics, 'eval-test', out_dir=tmp_path,
                           inputs={'artifact': 'a.jsonl'})
    assert j2.read_bytes() == first_json
    assert m2.read_bytes() == first_md
    payload = json.loads(first_json)
    assert payload['metrics']['coverage']['coverage'] == 0.75
    assert '| coverage.coverage | 0.75 |' in first_md.decode('utf-8')


def test_fuzzy_overlap_behavior():
    assert fuzzy_overlap('pedestrian', 'the pedestrian')      # substring
    assert not fuzzy_overlap('cyclist', 'a jogger')
    assert not fuzzy_overlap('', 'anything')
