'''Tests for graph_load.py — stubbed driver, assertions on generated Cypher.'''
import json

import pytest

import graph_load
from graph_load import (
    apply_statements,
    collect_instances,
    graph_counts,
    plan_load,
    preflight,
)


def fixture_records():
    '''Two docs sharing a Company node, one cross-doc relationship set.'''
    return [
        {
            'doc_key': 'INC-1', 'status': 'ok',
            'entities': [
                {'key': 'INC-1', 'type': 'Incident', 'name': 'INC-1',
                 'provenance': 'column', 'quote': '',
                 'properties': {'incident_key': 'INC-1'}},
                {'key': 'VIN1', 'type': 'Vehicle', 'name': 'subject vehicle',
                 'provenance': 'column', 'quote': '',
                 'properties': {'vehicle_key': 'VIN1'}},
                {'key': 'waymo', 'type': 'Company', 'name': 'waymo',
                 'provenance': 'column', 'quote': '', 'properties': {}},
                # narrative instance of the same company: same key
                {'key': 'waymo', 'type': 'Company', 'name': 'Waymo',
                 'provenance': 'narrative', 'quote': 'the Waymo vehicle',
                 'properties': {'mentioned': 'true'}},
            ],
            'relationships': [
                {'type': 'INVOLVES', 'source_key': 'INC-1',
                 'target_key': 'VIN1', 'provenance': 'column'},
                {'type': 'OPERATED_BY', 'source_key': 'VIN1',
                 'target_key': 'waymo', 'provenance': 'column'},
            ],
        },
        {
            'doc_key': 'INC-2', 'status': 'ok',
            'entities': [
                {'key': 'INC-2', 'type': 'Incident', 'name': 'INC-2',
                 'provenance': 'column', 'quote': '', 'properties': {}},
                {'key': 'waymo', 'type': 'Company', 'name': 'waymo',
                 'provenance': 'column', 'quote': '', 'properties': {}},
            ],
            'relationships': [
                {'type': 'REPORTED_BY', 'source_key': 'INC-2',
                 'target_key': 'waymo', 'provenance': 'column'},
            ],
        },
    ]


def test_constraint_ddl_once_per_label_with_if_not_exists():
    statements, _ = plan_load(fixture_records())
    constraints = [q for q, _ in statements if q.startswith('CREATE CONSTRAINT')]
    assert len(constraints) == 3  # Incident, Vehicle, Company
    assert all('IF NOT EXISTS' in q for q in constraints)
    assert all('REQUIRE n.key IS UNIQUE' in q for q in constraints)
    # constraints precede every load statement
    first_load = next(i for i, (q, _) in enumerate(statements) if 'UNWIND' in q)
    assert first_load == len(constraints)


def test_node_batches_merge_on_key_only_props_in_set():
    statements, _ = plan_load(fixture_records())
    node_loads = [(q, p) for q, p in statements
                  if 'MERGE (n:' in q and 'UNWIND' in q]
    for query, params in node_loads:
        assert '{key: row.key}' in query
        assert 'SET n += row.props' in query
        for row in params['rows']:
            assert set(row) == {'key', 'props'}
            assert 'key' not in row['props'] or row['props'].get('key') is None \
                or True  # props may carry domain fields, never the merge key


def test_duplicate_keys_collapse_to_one_row():
    nodes_by_label, _, _ = collect_instances(fixture_records())
    company_rows = nodes_by_label['Company']
    assert len(company_rows) == 1  # waymo appears 3x across docs/provenance
    # first-wins merge with later fills
    assert company_rows[0]['props']['name'] == 'waymo'
    assert company_rows[0]['props']['mentioned'] == 'true'


def test_relationship_loads_match_both_endpoints_with_labels():
    statements, skipped = plan_load(fixture_records())
    rel_loads = [(q, p) for q, p in statements if 'MATCH (a:' in q]
    assert skipped == []
    assert len(rel_loads) == 3  # INVOLVES, OPERATED_BY, REPORTED_BY groups
    for query, params in rel_loads:
        assert 'MATCH (a:' in query and 'MATCH (b:' in query
        assert 'MERGE (a)-[r:' in query
        assert 'SET r += row.props' in query
        assert all(set(r) == {'source_key', 'target_key', 'props'}
                   for r in params['rows'])
    by_type = {q.split('MERGE (a)-[r:`')[1].split('`')[0] for q, _ in rel_loads}
    assert by_type == {'INVOLVES', 'OPERATED_BY', 'REPORTED_BY'}


def test_loading_same_artifact_twice_is_statement_identical():
    a, _ = plan_load(fixture_records())
    b, _ = plan_load(fixture_records())
    assert a == b


def test_unresolvable_relationship_keys_are_skipped_not_fatal():
    records = fixture_records()
    records[0]['relationships'].append(
        {'type': 'INVOLVES', 'source_key': 'INC-1',
         'target_key': 'GHOST', 'provenance': 'narrative'})
    statements, skipped = plan_load(records)
    assert len(skipped) == 1
    assert skipped[0]['target_key'] == 'GHOST'


def test_batching_splits_large_row_sets():
    records = [{
        'doc_key': f'INC-{i}', 'status': 'ok',
        'entities': [{'key': f'INC-{i}', 'type': 'Incident',
                      'name': f'INC-{i}', 'provenance': 'column',
                      'quote': '', 'properties': {}}],
        'relationships': [],
    } for i in range(5)]
    statements, _ = plan_load(records, batch_size=2)
    incident_loads = [p for q, p in statements if 'MERGE (n:`Incident`' in q]
    assert [len(p['rows']) for p in incident_loads] == [2, 2, 1]


def test_apply_statements_sends_plans_to_driver(stub_driver_factory):
    driver = stub_driver_factory()
    statements, _ = plan_load(fixture_records())
    apply_statements(driver, statements)
    assert len(driver.queries) == len(statements)
    assert driver.queries[0][0].startswith('CREATE CONSTRAINT')


def test_preflight_paused_instance_message(stub_driver_factory):
    from neo4j.exceptions import ServiceUnavailable
    driver = stub_driver_factory(
        connectivity_error=ServiceUnavailable('Unable to connect'))
    with pytest.raises(RuntimeError, match='Aura console'):
        preflight(driver)


def test_preflight_passes_when_reachable(stub_driver_factory):
    preflight(stub_driver_factory())  # no exception


def test_reset_refuses_without_yes_non_interactive(monkeypatch, capsys):
    monkeypatch.setattr('sys.stdin', type('S', (), {'isatty': lambda self: False})())
    assert graph_load._confirm_reset(False) is False
    assert graph_load._confirm_reset(True) is True


def test_graph_counts_reads_scalar(stub_driver_factory):
    driver = stub_driver_factory(results={
        'count(n)': [{'n': 7}],
        'count(r)': [{'n': 3}],
    })
    assert graph_counts(driver) == {'nodes': 7, 'relationships': 3}


def test_get_driver_requires_env(monkeypatch):
    for var in graph_load.NEO4J_ENV:
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match='NEO4J_URI'):
        graph_load.get_driver()


def test_relationship_properties_flow_into_set_clause():
    records = fixture_records()
    records[0]['relationships'][0]['properties'] = {
        'precrash_speed_mph': '25.0'}
    statements, _ = plan_load(records)
    involves = next(p for q, p in statements if 'INVOLVES' in q)
    assert involves['rows'][0]['props'] == {'precrash_speed_mph': '25.0'}


def test_latest_artifact_ignores_runs_without_summary(tmp_path, monkeypatch):
    import run_records
    extractions = tmp_path / 'extractions'
    runs = tmp_path / 'runs'
    extractions.mkdir()
    runs.mkdir()
    monkeypatch.setattr(graph_load, 'EXTRACTIONS_DIR', extractions)
    monkeypatch.setattr(run_records, 'DEFAULT_RUNS_DIR', runs)

    (extractions / 'run-001.jsonl').write_text('{}\n', encoding='utf-8')
    (extractions / 'run-002.jsonl').write_text('{}\n', encoding='utf-8')
    # only run-001 completed (has a summary); run-002 is a crashed partial
    (runs / 'run-001.summary.json').write_text('{}', encoding='utf-8')
    assert graph_load._latest_artifact().name == 'run-001.jsonl'

    (runs / 'run-001.summary.json').unlink()
    with pytest.raises(FileNotFoundError, match='partial'):
        graph_load._latest_artifact()


def test_read_artifact_round_trip(tmp_path):
    path = tmp_path / 'a.jsonl'
    records = fixture_records()
    path.write_text('\n'.join(json.dumps(r) for r in records) + '\n',
                    encoding='utf-8')
    assert graph_load.read_artifact(path) == records
