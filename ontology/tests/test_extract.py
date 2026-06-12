'''Tests for extract.py — fan-out graph, artifact, run records. Stubbed LLM.'''
import hashlib
import json

import pytest

from corpus import Doc
from extract import (
    aggregate_counters,
    build_extraction_model,
    column_instances,
    extraction_prompt,
    golden_doc_keys,
    run_extraction,
    select_docs,
)
from llm import CachedLLM
from run_records import RunRecorder
from test_prune import narrative_schema

TEXT_1 = 'A pedestrian entered the roadway. The AV braked.'
TEXT_2 = 'The vehicle stopped at a red light without incident.'


def make_doc(key, text, skip_reason=None, row=None):
    return Doc(
        doc_key=key, report_id=key, same_incident_id=None,
        text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest(),
        skip_reason=skip_reason,
        row=row if row is not None else {
            'master_entity': 'waymo', 'VIN': f'VIN-{key}',
            'City': 'Phoenix', 'State': 'AZ',
            'weather_rain_clean': '1', 'Crash With': 'Passenger Car',
            'Highest Injury Severity Alleged': 'No Injuries Reported',
        })


def extraction_factory(prompt, schema):
    if 'pedestrian entered the roadway' in prompt:
        return schema(
            entities=[
                {'type': 'Pedestrian', 'name': 'pedestrian',
                 'supporting_quote': 'A pedestrian entered the roadway'},
                {'type': 'Vehicle', 'name': 'the AV',
                 'supporting_quote': 'The AV braked'},
            ],
            relationships=[
                {'type': 'STRUCK', 'source_type': 'Vehicle',
                 'source_name': 'the AV', 'target_type': 'Pedestrian',
                 'target_name': 'pedestrian',
                 'supporting_quote': 'The AV braked'},
            ])
    return schema(entities=[], relationships=[])


def run(tmp_path, docs, client, dry_run=False, recorder=None,
        max_concurrency=1, artifact_name='run.jsonl'):
    llm = CachedLLM(model_id='test-model', cache_dir=tmp_path / 'cache',
                    _client=client, _sleep=lambda s: None, dry_run=dry_run)
    artifact = tmp_path / 'extractions' / artifact_name
    state = run_extraction(docs, narrative_schema(), llm, artifact,
                           recorder=recorder, max_concurrency=max_concurrency)
    return llm, artifact, state


def read_artifact(path):
    return [json.loads(line) for line in
            path.read_text(encoding='utf-8').splitlines()]


def test_valid_extraction_lands_in_artifact_with_provenance(
        tmp_path, stub_llm_factory):
    client = stub_llm_factory(response_factory=extraction_factory)
    _, artifact, _ = run(tmp_path, [make_doc('INC-1', TEXT_1)], client)
    [record] = read_artifact(artifact)

    assert record['doc_key'] == 'INC-1'
    assert record['status'] == 'ok'
    assert record['text'] == TEXT_1
    provenances = {e['provenance'] for e in record['entities']}
    assert provenances == {'column', 'narrative'}
    narrative_ents = [e for e in record['entities']
                      if e['provenance'] == 'narrative']
    assert {e['type'] for e in narrative_ents} == {'Pedestrian', 'Vehicle'}
    assert all(e['quote'] for e in narrative_ents)
    struck = [r for r in record['relationships'] if r['type'] == 'STRUCK']
    assert len(struck) == 1


def test_column_instances_for_redacted_doc_no_llm_call(
        tmp_path, stub_llm_factory):
    client = stub_llm_factory()  # any call would blow up
    doc = make_doc('INC-9', '', skip_reason='skipped_redacted')
    _, artifact, state = run(tmp_path, [doc], client)
    [record] = read_artifact(artifact)

    assert client.calls == []
    assert record['status'] == 'skipped_redacted'
    assert record['entities']
    assert all(e['provenance'] == 'column' for e in record['entities'])
    types = {e['type'] for e in record['entities']}
    assert {'Incident', 'Vehicle', 'Company'} <= types


def test_column_instances_structure():
    doc = make_doc('INC-1', TEXT_1)
    doc.row['sv_precrash_speed_mph'] = 25.0
    entities, relationships, _ = column_instances(doc)
    by_type = {}
    for e in entities:
        by_type.setdefault(e.type, []).append(e)

    assert by_type['Incident'][0].key == 'INC-1'
    subject, partner = by_type['Vehicle']
    assert subject.key == 'VIN-INC-1'          # VIN preferred
    assert partner.key == 'INC-1:V1'           # crash partner never collides
    assert by_type['Company'][0].key == 'waymo'
    assert by_type['EnvironmentalCondition'][0].name == 'Rain'
    rel_types = {r.type for r in relationships}
    assert {'INVOLVES', 'OPERATED_BY', 'REPORTED_BY', 'OCCURRED_AT',
            'HAD_CONDITION', 'COLLIDED_WITH'} == rel_types
    assert all(r.provenance == 'column' for r in relationships)
    # Per-incident vehicle facts live on INVOLVES, never on the VIN-keyed
    # node (the same physical vehicle appears in many incidents).
    assert 'precrash_speed_mph' not in subject.properties
    sv_involves = next(r for r in relationships
                       if r.type == 'INVOLVES' and r.target_key == subject.key)
    assert sv_involves.properties['precrash_speed_mph'] == '25.0'


def test_column_instances_minimal_row():
    # Absent branches: no company, no location, no weather, no partner.
    doc = make_doc('INC-9', TEXT_2, row={})
    entities, relationships, _ = column_instances(doc)
    types = {e.type for e in entities}
    assert types == {'Incident', 'Vehicle'}   # only the always-present pair
    assert [r.type for r in relationships] == ['INVOLVES']
    subject = next(e for e in entities if e.type == 'Vehicle')
    assert subject.key == 'INC-9:SV'          # no VIN -> :SV key


def test_cache_hit_skips_stub_client(tmp_path, stub_llm_factory):
    docs = [make_doc('INC-1', TEXT_1)]
    run(tmp_path, docs, stub_llm_factory(response_factory=extraction_factory))
    second_client = stub_llm_factory()
    llm, artifact, _ = run(tmp_path, docs, second_client,
                           artifact_name='run2.jsonl')
    assert second_client.calls == []
    assert llm.stats['cache_hits'] == 1
    # artifact still written on the cached run
    assert len(read_artifact(artifact)) == 1


def test_one_docs_permanent_failure_does_not_abort_run(
        tmp_path, stub_llm_factory):
    # Doc 3's call fails permanently; the run completes, docs 1-2 carry
    # full extractions, and doc 3 is recorded as failed with its column
    # entities intact (the plan's failed_docs requirement).
    client = stub_llm_factory(response_factory=extraction_factory)
    docs = [make_doc('INC-1', TEXT_1), make_doc('INC-2', TEXT_2),
            make_doc('INC-3', 'A cyclist passed by.')]

    def failing_factory(prompt, schema):
        if 'cyclist' in prompt:
            raise _bad_request()
        return extraction_factory(prompt, schema)

    client.response_factory = failing_factory
    _, artifact, state = run(tmp_path, docs, client)
    records = {r['doc_key']: r for r in read_artifact(artifact)}
    assert set(records) == {'INC-1', 'INC-2', 'INC-3'}
    failed = records['INC-3']
    assert failed['status'] == 'failed'
    assert 'HTTP 400' in failed['error']
    assert failed['entities']  # column entities still present
    assert all(e['provenance'] == 'column' for e in failed['entities'])
    statuses = {r['doc_key']: r['status'] for r in state['results']}
    assert statuses == {'INC-1': 'ok', 'INC-2': 'ok', 'INC-3': 'failed'}


def _bad_request():
    e = RuntimeError('HTTP 400')
    e.status_code = 400
    return e


def test_dry_run_zero_calls_zero_writes(tmp_path, stub_llm_factory):
    client = stub_llm_factory()
    llm, artifact, state = run(
        tmp_path, [make_doc('INC-1', TEXT_1), make_doc('INC-2', TEXT_2)],
        client, dry_run=True)
    assert client.calls == []
    assert llm.stats['dry_run_misses'] == 2
    assert not artifact.exists()
    statuses = {r['status'] for r in state['results']}
    assert statuses == {'dry_run_miss'}


def test_run_record_contains_required_fields(tmp_path, stub_llm_factory):
    from run_records import file_sha256
    from schema_model import dump_schema
    schema_path = dump_schema(narrative_schema(), tmp_path / 'v001-test.yaml')
    recorder = RunRecorder(
        'extract', runs_dir=tmp_path / 'runs', schema_path=schema_path,
        schema_version='v001-test',
        prompt_version='p001', model_id='test-model',
        data_snapshot={'built_at': '2026-03-16'})
    client = stub_llm_factory(response_factory=extraction_factory)
    run(tmp_path, [make_doc('INC-1', TEXT_1)], client, recorder=recorder)
    llm_stats = {'cache_hits': 0, 'llm_calls': 1, 'retries': 0,
                 'dry_run_misses': 0}
    summary_path = recorder.write_summary(llm_stats=llm_stats)

    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    for field in ('run_id', 'stage', 'git_sha', 'schema_version',
                  'schema_sha256', 'prompt_version', 'model_id',
                  'data_snapshot', 'docs_recorded', 'elapsed_seconds',
                  'llm_stats'):
        assert field in summary, field
    # the tamper check pins the schema file's actual content hash (R13)
    assert summary['schema_sha256'] == file_sha256(schema_path)
    doc_records = [json.loads(line) for line in
                   (tmp_path / 'runs').glob('*.docs.jsonl').__next__()
                   .read_text(encoding='utf-8').splitlines()]
    assert doc_records[0]['doc_key'] == 'INC-1'
    assert 'counters' in doc_records[0]
    assert 'latency_seconds' in doc_records[0]


def test_select_docs_include_golden_supersets_golden_keys(tmp_path):
    docs = [make_doc(f'INC-{i}', TEXT_2) for i in range(6)]
    golden_dir = tmp_path / 'golden'
    golden_dir.mkdir()
    (golden_dir / 'dev.jsonl').write_text(
        json.dumps({'doc_key': 'INC-4'}) + '\n', encoding='utf-8')
    (golden_dir / 'heldout.jsonl').write_text(
        json.dumps({'doc_key': 'INC-5'}) + '\n', encoding='utf-8')

    selected = select_docs(docs, limit=2, include_golden=True,
                           golden_dir=golden_dir)
    keys = [d.doc_key for d in selected]
    assert keys[:2] == ['INC-0', 'INC-1']
    assert set(golden_doc_keys(golden_dir)) <= set(keys)

    missing = select_docs(docs[:3], limit=2, include_golden=False)
    assert len(missing) == 2


def test_select_docs_raises_on_absent_golden_key(tmp_path):
    golden_dir = tmp_path / 'golden'
    golden_dir.mkdir()
    (golden_dir / 'dev.jsonl').write_text(
        json.dumps({'doc_key': 'GHOST'}) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='GHOST'):
        select_docs([make_doc('INC-1', TEXT_2)], include_golden=True,
                    golden_dir=golden_dir)


def test_extraction_model_rejects_unknown_type():
    model = build_extraction_model(narrative_schema())
    with pytest.raises(Exception):
        model(entities=[{'type': 'Dinosaur', 'name': 'rex',
                         'supporting_quote': 'x'}])


def test_prompt_embeds_schema_and_text():
    prompt = extraction_prompt(narrative_schema(), 'NARRATIVE BODY')
    assert 'Pedestrian' in prompt
    assert '(Vehicle)-[:STRUCK]->(Pedestrian)' in prompt
    assert 'NARRATIVE BODY' in prompt


def test_aggregate_counters():
    totals, statuses = aggregate_counters([
        {'status': 'ok', 'counters': {'hallucination': 1}},
        {'status': 'ok', 'counters': {'hallucination': 2, 'quote_mismatch': 1}},
        {'status': 'skipped_redacted', 'counters': {}},
    ])
    assert totals == {'hallucination': 3, 'quote_mismatch': 1}
    assert statuses == {'ok': 2, 'skipped_redacted': 1}
