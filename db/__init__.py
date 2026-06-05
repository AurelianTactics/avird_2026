'''Postgres ingestion + treated-data pipeline for the NHTSA SGO dataset.

Modules:
    connection      SQLAlchemy engine from DATABASE_URL + ping().
    create_tables   idempotent DDL runner (create / reset).
    ingest_raw      CSVs -> superset frame -> append + batch record.
    build_treated   raw latest view -> treatment pipeline -> treated table.
    manifest        emit cleaning_manifest.json / column_dictionary.json.
    run_pipeline    CLI orchestration (create -> ingest -> build -> emit).

Treatment-side logic (dedupe flag, harmonization, targets) lives in the
flat ``eda/eda_utils_*`` modules per the repo convention; the db modules add
``eda/`` to ``sys.path`` and import them by bare name.
'''
