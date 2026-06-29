'''Tests for db.connection (engine/ping) and db.create_tables (schema DDL).

All tests run against a throwaway sqlite database so no live Postgres is
needed; the DDL is written to be portable across sqlite + Postgres.
'''
import pytest
from sqlalchemy import inspect, text

import connection
import create_tables


# ---------------------------------------------------------------------------
# U1: connection.get_engine / ping
# ---------------------------------------------------------------------------
def test_get_engine_returns_engine_when_url_set(sqlite_url):
    eng = connection.get_engine(sqlite_url)
    assert eng is not None
    assert eng.url.get_backend_name() == 'sqlite'


def test_get_engine_raises_when_url_unset(monkeypatch):
    monkeypatch.delenv(connection.DATABASE_URL_ENV, raising=False)
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        connection.get_engine()


def test_get_engine_reads_env_var(monkeypatch, sqlite_url):
    monkeypatch.setenv(connection.DATABASE_URL_ENV, sqlite_url)
    eng = connection.get_engine()
    assert eng.url.get_backend_name() == 'sqlite'


def test_ping_returns_true_against_sqlite(engine):
    assert connection.ping(engine) is True


def test_normalize_url_routes_to_psycopg_v3():
    assert connection._normalize_url(
        'postgres://u:p@h:5432/db'
    ) == 'postgresql+psycopg://u:p@h:5432/db'
    assert connection._normalize_url(
        'postgresql://u:p@h:5432/db'
    ) == 'postgresql+psycopg://u:p@h:5432/db'
    # sqlite + already-qualified URLs pass through untouched
    assert connection._normalize_url('sqlite:///x.db') == 'sqlite:///x.db'
    assert connection._normalize_url(
        'postgresql+psycopg://u@h/db'
    ) == 'postgresql+psycopg://u@h/db'


# ---------------------------------------------------------------------------
# U2: create_tables.create / reset  (schema DDL)
# ---------------------------------------------------------------------------
EXPECTED_TABLES = {
    'raw_incident_reports',
    'ingest_batches',
    'treated_incident_reports',
    'fault_analysis',
}
EXPECTED_VIEWS = {'raw_incident_reports_latest'}


def test_create_makes_all_objects(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    views = set(insp.get_view_names())
    assert EXPECTED_TABLES <= tables
    assert EXPECTED_VIEWS <= views


def test_create_is_idempotent(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    # second run must not raise and must leave the schema intact
    create_tables.create(engine, csv_paths=csv_paths)
    insp = inspect(engine)
    assert EXPECTED_TABLES <= set(insp.get_table_names())
    assert EXPECTED_VIEWS <= set(insp.get_view_names())


def test_raw_column_list_equals_union_of_headers(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    union = create_tables.source_column_union(csv_paths)
    insp = inspect(engine)
    cols = {c['name'] for c in insp.get_columns('raw_incident_reports')}
    # every source column present, none dropped
    assert set(union) <= cols
    # metadata columns added on top
    assert create_tables.METADATA_COLUMNS <= cols
    # no duplication: union has no repeats
    assert len(union) == len(set(union))


def test_fault_analysis_has_expected_columns(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    insp = inspect(engine)
    cols = {c['name'] for c in insp.get_columns('fault_analysis')}
    assert {
        'report_id',
        'fault_version',
        'is_av_at_fault',
        'av_fault_percentage',
        'short_explanation_of_decision',
        'model',
        'created_at',
    } <= cols


def test_fault_analysis_rejects_out_of_range_percentage(engine, csv_paths):
    from sqlalchemy.exc import IntegrityError

    create_tables.create(engine, csv_paths=csv_paths)
    # sqlite enforces CHECK constraints; a percentage outside [0,1] is rejected.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                'INSERT INTO fault_analysis '
                '(report_id, fault_version, av_fault_percentage, created_at) '
                "VALUES ('R1', 'v1', 2.0, '2026-06-25T00:00:00')"
            ))


def test_fault_analysis_allows_null_sentinel_row(engine, csv_paths):
    # A parse failure stores NULL verdict + NULL percentage; the 0..1 CHECK
    # passes on NULL, so the error-sentinel row is legal.
    create_tables.create(engine, csv_paths=csv_paths)
    with engine.begin() as conn:
        conn.execute(text(
            'INSERT INTO fault_analysis '
            '(report_id, fault_version, is_av_at_fault, av_fault_percentage, '
            'short_explanation_of_decision, created_at) '
            "VALUES ('R1', 'v1', NULL, NULL, 'Error in parse', "
            "'2026-06-25T00:00:00')"
        ))
    with engine.connect() as conn:
        n = conn.execute(text('SELECT COUNT(*) FROM fault_analysis')).scalar()
    assert n == 1


def test_fault_analysis_unique_key_blocks_duplicate(engine, csv_paths):
    from sqlalchemy.exc import IntegrityError

    create_tables.create(engine, csv_paths=csv_paths)
    with engine.begin() as conn:
        conn.execute(text(
            'INSERT INTO fault_analysis '
            '(report_id, fault_version, created_at) '
            "VALUES ('R1', 'v1', '2026-06-25T00:00:00')"
        ))
    # Same (report_id, fault_version) violates the UNIQUE key — re-runs must
    # upsert (ON CONFLICT), never blindly append a duplicate verdict.
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                'INSERT INTO fault_analysis '
                '(report_id, fault_version, created_at) '
                "VALUES ('R1', 'v1', '2026-06-26T00:00:00')"
            ))


def test_drop_all_drops_fault_analysis(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    drop_sql = (create_tables._SQL_DIR / '099_drop_all.sql').read_text()
    with engine.begin() as conn:
        create_tables._run_script(conn, drop_sql)
    insp = inspect(engine)
    assert 'fault_analysis' not in set(insp.get_table_names())


def test_reset_drops_and_recreates_empty(engine, csv_paths):
    create_tables.create(engine, csv_paths=csv_paths)
    with engine.begin() as conn:
        conn.execute(text(
            'INSERT INTO ingest_batches (batch_id, source_file, sha256, '
            'row_count, schema_version, ingested_at) '
            "VALUES ('b1', 'f.csv', 'abc', 1, 'early', '2026-01-01T00:00:00')"
        ))
    create_tables.reset(engine, csv_paths=csv_paths)
    insp = inspect(engine)
    assert EXPECTED_TABLES <= set(insp.get_table_names())
    with engine.connect() as conn:
        n_raw = conn.execute(
            text('SELECT COUNT(*) FROM raw_incident_reports')
        ).scalar()
        n_batches = conn.execute(
            text('SELECT COUNT(*) FROM ingest_batches')
        ).scalar()
    assert n_raw == 0
    assert n_batches == 0
