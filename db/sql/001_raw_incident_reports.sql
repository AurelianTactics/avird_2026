-- raw_incident_reports: a single superset of BOTH SGO schema versions.
--
-- Every *source* column is stored as nullable TEXT. Storing raw as TEXT
-- preserves source fidelity and side-steps the known cross-version dtype
-- drift (Model Year float/int, SV Precrash Speed float/int); typing happens
-- only in the treated layer.
--
-- The source-column list is generated from the UNION of the two CSV headers
-- at create time and injected in place of the marker on the next line, so the
-- ~165 column names are never hand-maintained here. The metadata columns below
-- are fixed and always appended after the source columns.
CREATE TABLE IF NOT EXISTS raw_incident_reports (
{{SOURCE_COLUMNS}},
    "ingest_batch_id" TEXT NOT NULL,
    "source_file"     TEXT NOT NULL,
    "schema_version"  TEXT NOT NULL,
    "ingested_at"     TEXT NOT NULL
);
