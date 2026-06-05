'''Tests for db.build_treated against a throwaway sqlite database.'''
import pandas as pd
import pytest
from sqlalchemy import inspect, text

import build_treated
import create_tables
import ingest_raw


CANONICAL_ROWS = 2344
LATEST_ROWS = None  # computed per-fixture (distinct natural keys)


@pytest.fixture
def populated_engine(engine, csv_paths):
    '''Schema created + both CSVs ingested -> ready to build treated.'''
    create_tables.create(engine, csv_paths=csv_paths)
    ingest_raw.ingest_all(engine, csv_paths)
    return engine


def _latest_count(engine):
    with engine.connect() as conn:
        return conn.execute(
            text('SELECT COUNT(*) FROM raw_incident_reports_latest')
        ).scalar()


def _treated_df(engine):
    with engine.connect() as conn:
        return pd.read_sql('SELECT * FROM treated_incident_reports', conn)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_treated_row_count_equals_latest_and_canonical_2344(populated_engine):
    result = build_treated.build_treated(populated_engine)
    assert result['treated_rows'] == _latest_count(populated_engine)
    assert result['canonical_rows'] == CANONICAL_ROWS
    treated = _treated_df(populated_engine)
    assert len(treated) == result['treated_rows']


def test_expected_columns_present(populated_engine):
    build_treated.build_treated(populated_engine)
    cols = set(_treated_df(populated_engine).columns)
    # flags
    assert {'is_latest_of_multiple_report', 'has_multiple_reports'} <= cols
    # treatments
    assert {'master_entity', 'Make Model'} <= cols
    # harmonized
    import eda_utils_harmonize as hz
    assert set(hz.harmonized_columns()) <= cols
    # all 7 targets
    expected_targets = {
        'No Injury Reported', 'Injury Reported', 'Multi Class Injury',
        'Binary Airbag Deployed', 'Binary Vehicle Towed', 'SV Speed >= 10',
        'Potential Non-Trivial Accident',
    }
    assert expected_targets <= cols
    # provenance
    assert {'source_batch_ids', 'built_at'} <= cols


def test_multi_report_incident_one_canonical_with_merged_narrative(populated_engine):
    build_treated.build_treated(populated_engine)
    treated = _treated_df(populated_engine)
    # every retained natural key appears once (latest view already dedups keys),
    # and exactly the canonical subset is flagged
    assert int(treated['is_latest_of_multiple_report'].sum()) == CANONICAL_ROWS
    # canonical rows of multi-report incidents carry a merged narrative
    multi_canon = treated[
        (treated['is_latest_of_multiple_report'] == 1)
        & (treated['has_multiple_reports'] == 1)
    ]
    assert multi_canon['Narrative - Same Incident ID'].notna().any()


# ---------------------------------------------------------------------------
# Steps / manifest inputs
# ---------------------------------------------------------------------------
def test_steps_recorded_in_order_with_outputs(populated_engine):
    result = build_treated.build_treated(populated_engine)
    names = [s['step'] for s in result['steps']]
    assert names == [
        'promote_typed_columns', 'dedupe_flag', 'treatments',
        'harmonize_engagement', 'harmonize_belted', 'harmonize_weather',
        'harmonize_roadway', 'harmonize_lighting', 'targets',
    ]
    for step in result['steps']:
        assert len(step['output_columns']) >= 1
        assert step['rows_in'] > 0


# ---------------------------------------------------------------------------
# Idempotency (replace semantics) -- data identical, ignoring built_at
# ---------------------------------------------------------------------------
def test_rebuild_is_idempotent(populated_engine):
    build_treated.build_treated(populated_engine)
    first = _treated_df(populated_engine).drop(columns=['built_at'])
    build_treated.build_treated(populated_engine)
    second = _treated_df(populated_engine).drop(columns=['built_at'])
    pd.testing.assert_frame_equal(first, second)


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------
def test_build_aborts_when_latest_empty(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)  # schema but no rows
    with pytest.raises(ValueError, match='empty'):
        build_treated.build_treated(engine)
