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
