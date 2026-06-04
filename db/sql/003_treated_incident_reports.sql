-- treated_incident_reports: derived layer, fully rebuilt from the raw
-- `latest` view each run (see build_treated.py). This DDL defines the
-- empty-state contract + the typed "promoted" columns; build_treated writes
-- the full derived frame (raw passthrough + flags + cleaned + harmonized +
-- target columns) via pandas to_sql(if_exists='replace'), which recreates the
-- table from the DataFrame dtypes. The promoted columns below are coerced to
-- real types in build_treated so they land as DATE/NUMERIC/BOOLEAN.
CREATE TABLE IF NOT EXISTS treated_incident_reports (
    "Report ID"                    TEXT,
    "Report Version"               TEXT,
    "incident_date"                DATE,
    "lat_numeric"                  NUMERIC,
    "lon_numeric"                  NUMERIC,
    "sv_precrash_speed_mph"        NUMERIC,
    "is_latest_of_multiple_report" BOOLEAN,
    "has_multiple_reports"         BOOLEAN,
    "source_batch_ids"             TEXT,
    "built_at"                     TEXT
);
