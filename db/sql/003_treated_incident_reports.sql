-- treated_incident_reports: derived layer, fully rebuilt from the raw
-- `latest` view each run (see build_treated.py). This DDL defines the
-- empty-state contract + the typed "promoted"/flag columns; build_treated
-- writes the full derived frame (raw passthrough + flags + cleaned +
-- harmonized + target columns) via pandas to_sql(if_exists='replace'), which
-- recreates the table on each build. The promoted + flag columns below are
-- given these same explicit SQL types at write time via to_sql(dtype=...) --
-- see build_treated.TREATED_COLUMN_TYPES, which must stay in sync with the
-- column->type pairs here -- so the rebuilt table honors this contract instead
-- of falling back to pandas-inferred types. Remaining columns land as TEXT.
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
