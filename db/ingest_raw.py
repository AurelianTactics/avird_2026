'''Raw ingestion: CSV -> superset frame -> append + ingest_batches record.

Each CSV is loaded as its own *batch*. Rows are aligned to the raw table's
superset column set (missing columns -> SQL NULL) and stored as TEXT to
preserve source fidelity. Three safety layers keep repeated runs (especially
while iterating on Railway) from corrupting the table:

1. sha256 guard   -- re-ingesting the same file is a 0-row no-op unless force.
2. fail loud      -- a CSV with a column absent from the raw table aborts the
                     batch (names the columns, writes nothing). Schema growth
                     is a deliberate DDL edit, not an automatic side effect.
3. transactional  -- the row append and the ingest_batches row commit together;
                     a failure anywhere rolls the whole batch back (no orphans).

Note: unlike eda_utils_sgo.load_and_concat_csvs (which lets pandas infer
dtypes and coerces e.g. Model Year to float), ingest reads every column as a
string (dtype=str) so the TEXT raw layer keeps the source text verbatim;
typing happens only in the treated layer.
'''
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import inspect, text

import create_tables

RAW_TABLE = 'raw_incident_reports'
BATCHES_TABLE = 'ingest_batches'

# A later-schema-only column used to tell the two schema versions apart.
_LATER_MARKER_COLUMN = 'Engagement Status'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def compute_sha256(path):
    '''Hex sha256 of the file's bytes.'''
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def detect_schema_version(columns):
    '''early vs later schema, by presence of a later-only marker column.'''
    return 'later' if _LATER_MARKER_COLUMN in set(columns) else 'early'


def raw_source_columns(engine, table=RAW_TABLE):
    '''The raw table's source columns (all columns minus the fixed metadata).'''
    insp = inspect(engine)
    cols = [c['name'] for c in insp.get_columns(table)]
    return [c for c in cols if c not in create_tables.METADATA_COLUMNS]


def _sha256_already_ingested(conn, sha256):
    row = conn.execute(
        text(f'SELECT 1 FROM {BATCHES_TABLE} WHERE sha256 = :s'),
        {'s': sha256},
    ).first()
    return row is not None


def _blanks_to_null(df):
    '''Whitespace-only and NaN cells -> None (SQL NULL); keep other text.'''
    cleaned = df.replace(r'^\s*$', np.nan, regex=True)
    return cleaned.astype(object).where(cleaned.notna(), None)


def _write_batch_row(conn, batch):
    '''Insert one ingest_batches row. Separate function so tests can patch it
    to raise and prove the surrounding transaction rolls back.'''
    conn.execute(
        text(
            f'INSERT INTO {BATCHES_TABLE} '
            '(batch_id, source_file, sha256, row_count, schema_version, '
            ' ingested_at, notes) '
            'VALUES (:batch_id, :source_file, :sha256, :row_count, '
            ':schema_version, :ingested_at, :notes)'
        ),
        batch,
    )


# ---------------------------------------------------------------------------
# Per-file ingest
# ---------------------------------------------------------------------------
def ingest_file(engine, path, force=False, table=RAW_TABLE):
    '''Ingest one CSV as a batch. Returns a result dict; see module docstring
    for the guard / fail-loud / transactional semantics.'''
    path = Path(path)
    source_file = path.name
    sha256 = compute_sha256(path)

    # sha256 double-ingest guard.
    with engine.connect() as conn:
        if _sha256_already_ingested(conn, sha256) and not force:
            print(f'[ingest] skip {source_file}: sha256 already ingested '
                  f'(use force=True to re-ingest)')
            return {'source_file': source_file, 'sha256': sha256,
                    'row_count': 0, 'skipped': True, 'batch_id': None,
                    'schema_version': None}

    # Read every column as text for raw fidelity.
    df = pd.read_csv(path, dtype=str)
    schema_version = detect_schema_version(df.columns)

    # Fail loud: no incoming column may be absent from the raw table.
    allowed = set(raw_source_columns(engine, table))
    unknown = [c for c in df.columns if c not in allowed]
    if unknown:
        raise ValueError(
            f'{source_file}: {len(unknown)} column(s) not present in '
            f'{table}; aborting batch (wrote nothing). Extend the DDL '
            f'deliberately and re-run. Offending columns: {unknown}'
        )

    # Align to the superset column set (missing -> NULL) and clean blanks.
    source_cols = raw_source_columns(engine, table)
    aligned = _blanks_to_null(df.reindex(columns=source_cols))

    # Stamp metadata. Build it as its own frame and concat once so we don't
    # fragment the ~165-column source frame with repeated single-column inserts.
    batch_id = uuid.uuid4().hex
    ingested_at = datetime.now(timezone.utc).isoformat()
    meta = pd.DataFrame(
        {
            'ingest_batch_id': batch_id,
            'source_file': source_file,
            'schema_version': schema_version,
            'ingested_at': ingested_at,
        },
        index=aligned.index,
    )
    aligned = pd.concat([aligned, meta], axis=1)

    row_count = len(aligned)
    notes = (f'{schema_version} schema; {df.shape[1]} source columns; '
             f'{row_count} rows')
    batch = {
        'batch_id': batch_id, 'source_file': source_file, 'sha256': sha256,
        'row_count': row_count, 'schema_version': schema_version,
        'ingested_at': ingested_at, 'notes': notes,
    }

    # Transactional: append rows AND write the batch row together.
    with engine.begin() as conn:
        aligned.to_sql(table, conn, if_exists='append', index=False)
        _write_batch_row(conn, batch)

    print(f'[ingest] {source_file}: appended {row_count} rows '
          f'({schema_version} schema), batch {batch_id}')
    return {'source_file': source_file, 'sha256': sha256,
            'row_count': row_count, 'skipped': False, 'batch_id': batch_id,
            'schema_version': schema_version}


def ingest_all(engine, csv_paths=create_tables.DEFAULT_CSV_PATHS, force=False):
    '''Ingest every CSV in order. Returns the list of per-file result dicts.'''
    return [ingest_file(engine, p, force=force) for p in csv_paths]
