-- raw_incident_reports_latest: the newest batch's row per natural key
-- (Report ID, Report Version). The site reads this view so "pull newest"
-- needs no client-side logic. Append-only history stays in the base table.
--
-- DROP + CREATE (rather than CREATE OR REPLACE / CREATE ... IF NOT EXISTS) is
-- used because those spellings are not portable across sqlite and Postgres;
-- DROP VIEW IF EXISTS + CREATE VIEW is, and is idempotent.
--
-- The helper column `_latest_rank` is exposed by the view; build_treated drops
-- it after reading.
DROP VIEW IF EXISTS raw_incident_reports_latest;
CREATE VIEW raw_incident_reports_latest AS
SELECT * FROM (
    SELECT r.*,
           ROW_NUMBER() OVER (
               PARTITION BY "Report ID", "Report Version"
               ORDER BY "ingested_at" DESC, "ingest_batch_id" DESC
           ) AS _latest_rank
    FROM raw_incident_reports r
) ranked
WHERE _latest_rank = 1;
