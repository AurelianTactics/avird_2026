'''Tests for db.ingest_raw against a throwaway sqlite database.'''
import pandas as pd
import pytest
from sqlalchemy import text

import create_tables
import ingest_raw


EARLY_ROWS = 2295
LATER_ROWS = 825
TOTAL_ROWS = EARLY_ROWS + LATER_ROWS  # 3120


def _count(engine, sql, params=None):
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


@pytest.fixture
def ready_engine(engine, csv_paths):
    '''An engine with the schema created (no rows yet).'''
    create_tables.create(engine, csv_paths=csv_paths)
    return engine


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_ingest_both_csvs_row_and_batch_counts(ready_engine, csv_paths):
    results = ingest_raw.ingest_all(ready_engine, csv_paths)
    assert [r['row_count'] for r in results] == [EARLY_ROWS, LATER_ROWS]
    assert _count(ready_engine, 'SELECT COUNT(*) FROM raw_incident_reports') == TOTAL_ROWS
    assert _count(ready_engine, 'SELECT COUNT(*) FROM ingest_batches') == 2
    # schema_version recorded per batch
    with ready_engine.connect() as conn:
        versions = dict(conn.execute(text(
            'SELECT schema_version, row_count FROM ingest_batches'
        )).all())
    assert versions == {'early': EARLY_ROWS, 'later': LATER_ROWS}


def test_cross_version_columns_are_null(ready_engine, csv_paths):
    ingest_raw.ingest_all(ready_engine, csv_paths)
    # 'ADS Equipped?' is early-only -> NULL for every later row
    later_nonnull = _count(
        ready_engine,
        'SELECT COUNT(*) FROM raw_incident_reports '
        "WHERE schema_version = 'later' AND \"ADS Equipped?\" IS NOT NULL",
    )
    assert later_nonnull == 0
    # 'Engagement Status' is later-only -> NULL for every early row
    early_nonnull = _count(
        ready_engine,
        'SELECT COUNT(*) FROM raw_incident_reports '
        "WHERE schema_version = 'early' AND \"Engagement Status\" IS NOT NULL",
    )
    assert early_nonnull == 0


# ---------------------------------------------------------------------------
# Guard / force
# ---------------------------------------------------------------------------
def test_reingest_same_file_skips_without_force(ready_engine, csv_paths):
    ingest_raw.ingest_file(ready_engine, csv_paths[0])
    res = ingest_raw.ingest_file(ready_engine, csv_paths[0])
    assert res['skipped'] is True
    assert res['row_count'] == 0
    assert _count(ready_engine, 'SELECT COUNT(*) FROM raw_incident_reports') == EARLY_ROWS
    assert _count(ready_engine, 'SELECT COUNT(*) FROM ingest_batches') == 1


def test_reingest_with_force_appends_again(ready_engine, csv_paths):
    ingest_raw.ingest_file(ready_engine, csv_paths[0])
    res = ingest_raw.ingest_file(ready_engine, csv_paths[0], force=True)
    assert res['skipped'] is False
    assert _count(ready_engine, 'SELECT COUNT(*) FROM raw_incident_reports') == 2 * EARLY_ROWS
    assert _count(ready_engine, 'SELECT COUNT(*) FROM ingest_batches') == 2


# ---------------------------------------------------------------------------
# Fail loud on unknown column
# ---------------------------------------------------------------------------
def test_unknown_column_aborts_and_writes_nothing(ready_engine, tmp_path):
    bad = tmp_path / 'bad.csv'
    pd.DataFrame({
        'Report ID': ['r1'],
        'Report Version': ['1'],
        'A Brand New Column': ['surprise'],
    }).to_csv(bad, index=False)

    with pytest.raises(ValueError, match='A Brand New Column'):
        ingest_raw.ingest_file(ready_engine, bad)

    assert _count(ready_engine, 'SELECT COUNT(*) FROM raw_incident_reports') == 0
    assert _count(ready_engine, 'SELECT COUNT(*) FROM ingest_batches') == 0


# ---------------------------------------------------------------------------
# Transactional rollback
# ---------------------------------------------------------------------------
def test_rollback_leaves_table_unchanged(ready_engine, csv_paths, monkeypatch):
    def boom(conn, batch):
        raise RuntimeError('simulated batch-row failure')

    monkeypatch.setattr(ingest_raw, '_write_batch_row', boom)
    with pytest.raises(RuntimeError, match='simulated'):
        ingest_raw.ingest_file(ready_engine, csv_paths[0])

    # full rollback: neither the appended rows nor the batch row survive
    assert _count(ready_engine, 'SELECT COUNT(*) FROM raw_incident_reports') == 0
    assert _count(ready_engine, 'SELECT COUNT(*) FROM ingest_batches') == 0


# ---------------------------------------------------------------------------
# Blanks -> NULL
# ---------------------------------------------------------------------------
def test_blanks_and_whitespace_become_null(ready_engine, tmp_path):
    csv = tmp_path / 'blanks.csv'
    # Make is empty-string; Model is whitespace-only; both must land as NULL.
    csv.write_text(
        'Report ID,Report Version,Make,Model\n'
        'r1,1,,   \n'
    )
    ingest_raw.ingest_file(ready_engine, csv)
    with ready_engine.connect() as conn:
        row = conn.execute(text(
            'SELECT "Make", "Model" FROM raw_incident_reports WHERE "Report ID" = \'r1\''
        )).first()
    assert row == (None, None)


# ---------------------------------------------------------------------------
# Latest view
# ---------------------------------------------------------------------------
def test_latest_view_one_row_per_natural_key(ready_engine, csv_paths):
    ingest_raw.ingest_all(ready_engine, csv_paths)
    distinct_keys = _count(
        ready_engine,
        'SELECT COUNT(*) FROM (SELECT DISTINCT "Report ID", "Report Version" '
        'FROM raw_incident_reports) k',
    )
    view_rows = _count(ready_engine, 'SELECT COUNT(*) FROM raw_incident_reports_latest')
    assert view_rows == distinct_keys
    # the view must not return duplicate natural keys
    dup = _count(
        ready_engine,
        'SELECT COUNT(*) FROM (SELECT "Report ID", "Report Version", '
        'COUNT(*) c FROM raw_incident_reports_latest '
        'GROUP BY "Report ID", "Report Version" HAVING COUNT(*) > 1) d',
    )
    assert dup == 0
