# `db/` — Postgres ingest + treated-data pipeline

Loads the two NHTSA SGO CSVs (`data/nhtsa/*.csv`) into a Railway-hosted
Postgres database as one append-only **raw** superset table (every column
nullable TEXT, batch-tracked), then derives a **treated** table (dedupe flag +
treatments + harmonization + 7 targets) and emits a machine-readable cleaning
manifest the site renders.

```
data/nhtsa/*.csv ─► ingest_raw.py ─► raw_incident_reports  ─► raw_incident_reports_latest (view)
                                 └──► ingest_batches
                                            │
                       build_treated.py ────┴─► treated_incident_reports
                                                        │
                                          manifest.py ──┴─► docs/data-dictionary/*.json
```

Orchestrated end-to-end by `run_pipeline.py`. Each stage is independently
runnable and idempotent.

## Env setup

1. Set `DATABASE_URL` in a `.env` file at the repo root (the file is gitignored).
   `postgres://`, `postgresql://`, and `postgresql+psycopg://` schemes are all
   accepted (the first two are rewritten to use psycopg v3).
   ```env
   DATABASE_URL=postgresql://user:pass@host:port/dbname
   ```
2. Install / refresh the shared uv env (adds `sqlalchemy` + `psycopg[binary]`
   on top of the existing requirements):
   ```bash
   uv pip install -r ../my-uv-envs/avird-2026-eda/requirements.txt
   ```
   See `eda/ADS_to_2026_03_16/EDA_README.md` for the full uv workflow.

## Run modes

```bash
# Default: preflight -> create -> ingest -> build -> emit
python db/run_pipeline.py

# Single stages
python db/run_pipeline.py --create-only
python db/run_pipeline.py --ingest-only
python db/run_pipeline.py --build-only
python db/run_pipeline.py --emit-only

# Re-ingest a file even if its sha256 is already on record
python db/run_pipeline.py --ingest-only --force

# Clean slate: DROP every object, recreate, then run the full pipeline.
# Destructive; refuses in non-interactive mode without --yes.
python db/run_pipeline.py --reset --yes
```

## Layout

```
db/
  connection.py       SQLAlchemy engine from DATABASE_URL + ping()
  create_tables.py    Idempotent DDL runner (create / reset)
  ingest_raw.py       CSV -> superset frame -> append + ingest_batches
  build_treated.py    raw_latest -> treatment pipeline -> treated table
  manifest.py         emit cleaning_manifest.json + column_dictionary.json
  run_pipeline.py     CLI: preflight -> create -> ingest -> build -> emit
  sql/                Plain DDL files; raw column list is generated from CSV headers
  RAILWAY_SETUP.md    Step-by-step instructions for the Railway side of the work
  tests/              sqlite-backed tests for every module
```

Treatment-side logic (dedupe flag, harmonization, targets) lives in
`eda/eda_utils_*.py` per the repo's flat-module convention. The db modules
add `eda/` to `sys.path` and import them by bare name.

## Tests

```bash
python -m pytest db/tests eda/tests -q
```

All tests run against an in-memory sqlite database; the DDL is dialect-portable
across sqlite + Postgres.

## Cleaning artifacts

`docs/data-dictionary/cleaning_manifest.json` and `column_dictionary.json` are
generated on every full run (or via `--emit-only`). They are the single source
of truth for the future data-dictionary page on the site.
