-- Teardown for the guarded --reset path. Order matters: drop the view first,
-- then the tables. Every statement is IF EXISTS so it is safe on a clean DB.
DROP VIEW IF EXISTS raw_incident_reports_latest;
DROP TABLE IF EXISTS treated_incident_reports;
DROP TABLE IF EXISTS ingest_batches;
DROP TABLE IF EXISTS raw_incident_reports;
