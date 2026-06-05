'''Tests for db.manifest (cleaning manifest + column dictionary).'''
import json

import pytest

import build_treated
import create_tables
import ingest_raw
import manifest


@pytest.fixture
def built_engine(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    ingest_raw.ingest_all(engine, csv_paths)
    return engine


def test_emit_writes_both_files_and_they_are_valid_json(built_engine, tmp_path):
    result = build_treated.build_treated(built_engine)
    paths = manifest.emit(built_engine, result, out_dir=tmp_path)
    cleaning = json.loads(open(paths['cleaning_manifest']).read())
    columns = json.loads(open(paths['column_dictionary']).read())
    assert 'generated_at' in cleaning and cleaning['generated_at']
    assert 'generated_at' in columns and columns['generated_at']
    assert cleaning['source_batch_ids'] and len(cleaning['source_batch_ids']) == 2
    assert columns['source_batch_ids'] == cleaning['source_batch_ids']


def test_cleaning_manifest_has_one_entry_per_pipeline_step_with_outputs(built_engine, tmp_path):
    result = build_treated.build_treated(built_engine)
    paths = manifest.emit(built_engine, result, out_dir=tmp_path)
    cleaning = json.loads(open(paths['cleaning_manifest']).read())
    names = [s['step'] for s in cleaning['steps']]
    assert names == [s['step'] for s in result['steps']]
    for step in cleaning['steps']:
        assert step['output_columns'], f"step {step['step']} has no output columns"


def test_engagement_and_lighting_caveats_attached_to_steps(built_engine, tmp_path):
    result = build_treated.build_treated(built_engine)
    paths = manifest.emit(built_engine, result, out_dir=tmp_path)
    cleaning = json.loads(open(paths['cleaning_manifest']).read())
    by_step = {s['step']: s for s in cleaning['steps']}
    assert 'caveat' in by_step['harmonize_engagement']
    assert 'caveat' in by_step['harmonize_lighting']
    assert 'mismatch' in by_step['harmonize_engagement']['caveat'].lower()


def test_every_treated_column_has_a_dictionary_entry(built_engine, tmp_path):
    import pandas as pd
    from sqlalchemy import text as _t
    result = build_treated.build_treated(built_engine)
    paths = manifest.emit(built_engine, result, out_dir=tmp_path)
    columns = json.loads(open(paths['column_dictionary']).read())
    entry_names = {c['name'] for c in columns['columns']}
    with built_engine.connect() as conn:
        actual = set(pd.read_sql(_t('SELECT * FROM treated_incident_reports LIMIT 0'),
                                 conn).columns)
    assert entry_names == actual  # no orphans either direction


def test_source_type_tagging(built_engine, tmp_path):
    result = build_treated.build_treated(built_engine)
    paths = manifest.emit(built_engine, result, out_dir=tmp_path)
    columns = json.loads(open(paths['column_dictionary']).read())
    by_name = {c['name']: c for c in columns['columns']}

    # targets
    for tname in ['No Injury Reported', 'Injury Reported', 'Multi Class Injury',
                  'Binary Airbag Deployed', 'Binary Vehicle Towed',
                  'SV Speed >= 10', 'Potential Non-Trivial Accident']:
        assert by_name[tname]['source_type'] == 'target'

    # flags
    for fname in ['is_latest_of_multiple_report', 'has_multiple_reports']:
        assert by_name[fname]['source_type'] == 'flag'

    # harmonized: every *_clean column from eda_utils_harmonize
    import eda_utils_harmonize as hz
    for hname in hz.harmonized_columns():
        assert by_name[hname]['source_type'] == 'harmonized'

    # cleaned: ' Clean'-suffixed treatment columns
    assert by_name['Operating Entity Clean']['source_type'] == 'cleaned'
    assert by_name['master_entity']['source_type'] == 'cleaned'

    # provenance
    assert by_name['source_batch_ids']['source_type'] == 'provenance'
    assert by_name['built_at']['source_type'] == 'provenance'

    # raw passthrough
    assert by_name['Report ID']['source_type'] == 'raw'


def test_lighting_clean_carries_caveat(built_engine, tmp_path):
    result = build_treated.build_treated(built_engine)
    paths = manifest.emit(built_engine, result, out_dir=tmp_path)
    columns = json.loads(open(paths['column_dictionary']).read())
    by_name = {c['name']: c for c in columns['columns']}
    assert 'caveat' in by_name['lighting_clean']
    assert 'early' in by_name['lighting_clean']['caveat'].lower()
