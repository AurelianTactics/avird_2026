'''Idempotent DDL runner for the SGO ingest schema.

`create(engine)` runs the SQL files under ``db/sql/`` so the raw table, the
batch-metadata table, the treated table and the latest view exist (safe to
re-run). `reset(engine)` drops everything first, then recreates -- it is
destructive and only ever invoked behind the explicit ``--reset`` flag.

The raw table's ~165 source columns are generated from the UNION of the two
CSV headers at create time, so the column names never have to be
hand-maintained in SQL.
'''
from pathlib import Path

import pandas as pd
from sqlalchemy import text

_HERE = Path(__file__).resolve().parent
_SQL_DIR = _HERE / 'sql'
_REPO_ROOT = _HERE.parent
_DATA_DIR = _REPO_ROOT / 'data' / 'nhtsa'

DEFAULT_CSV_PATHS = (
    _DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_to_2025_06_16.csv',
    _DATA_DIR / 'SGO-2021-01_Incident_Reports_ADS_2025_06_16_to_2026_03_16.csv',
)

# Fixed metadata columns appended to every raw row (must match 001_*.sql).
METADATA_COLUMNS = frozenset(
    {'ingest_batch_id', 'source_file', 'schema_version', 'ingested_at'}
)

_SOURCE_COLUMNS_MARKER = '{{SOURCE_COLUMNS}}'


# ---------------------------------------------------------------------------
# Column-set derivation
# ---------------------------------------------------------------------------
def read_header(path):
    '''Return the column names of a CSV without loading its rows.'''
    return list(pd.read_csv(path, nrows=0).columns)


def source_column_union(csv_paths=DEFAULT_CSV_PATHS):
    '''Ordered union of all CSV headers: first file's order, then any
    columns that appear only in later files, appended in first-seen order.
    No duplicates.'''
    seen = []
    for path in csv_paths:
        for col in read_header(path):
            if col not in seen:
                seen.append(col)
    return seen


def _quote_ident(name):
    '''Double-quote a SQL identifier, escaping any embedded double quotes.'''
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def build_raw_ddl(csv_paths=DEFAULT_CSV_PATHS):
    '''Fill 001_raw_incident_reports.sql's {{SOURCE_COLUMNS}} marker with the
    generated source-column list (every column nullable TEXT).'''
    template = (_SQL_DIR / '001_raw_incident_reports.sql').read_text()
    columns = source_column_union(csv_paths)
    lines = [f'    {_quote_ident(c)} TEXT' for c in columns]
    return template.replace(_SOURCE_COLUMNS_MARKER, ',\n'.join(lines))


# ---------------------------------------------------------------------------
# Statement execution
# ---------------------------------------------------------------------------
def _split_statements(sql):
    '''Split a SQL script into individual statements. Comment lines are
    stripped *first* (so a ';' inside a `--` comment can't leak a fragment into
    a statement), then we split on ';'. Our DDL contains no semicolons inside
    string literals, so this is safe and keeps us portable across DBAPIs that
    execute one statement per call (e.g. sqlite3).'''
    no_comments = '\n'.join(
        ln for ln in sql.splitlines() if not ln.strip().startswith('--')
    )
    return [stmt.strip() for stmt in no_comments.split(';') if stmt.strip()]


def _run_script(conn, sql):
    for stmt in _split_statements(sql):
        conn.execute(text(stmt))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def create(engine, csv_paths=DEFAULT_CSV_PATHS):
    '''Create all tables + the latest view if absent. Safe to re-run.'''
    raw_ddl = build_raw_ddl(csv_paths)
    batches_ddl = (_SQL_DIR / '002_ingest_batches.sql').read_text()
    treated_ddl = (_SQL_DIR / '003_treated_incident_reports.sql').read_text()
    view_ddl = (_SQL_DIR / '004_raw_latest_view.sql').read_text()

    with engine.begin() as conn:
        _run_script(conn, raw_ddl)
        _run_script(conn, batches_ddl)
        _run_script(conn, treated_ddl)
        _run_script(conn, view_ddl)


def reset(engine, csv_paths=DEFAULT_CSV_PATHS):
    '''DROP every object, then recreate. DESTRUCTIVE -- gated behind --reset.'''
    drop_sql = (_SQL_DIR / '099_drop_all.sql').read_text()
    with engine.begin() as conn:
        _run_script(conn, drop_sql)
    create(engine, csv_paths=csv_paths)
