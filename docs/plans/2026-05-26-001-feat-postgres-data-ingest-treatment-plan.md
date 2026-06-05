---
title: "feat: Postgres ingestion + treated-data pipeline for NHTSA SGO data"
type: feat
status: active
date: 2026-05-26
origin: docs/brainstorms/nhtsa-crash-project-requirements.md
---

# feat: Postgres ingestion + treated-data pipeline for NHTSA SGO data

## Summary

Build a reproducible Python pipeline in this repo that loads both NHTSA SGO CSVs into a single superset **raw** table (append-only, batch-tracked) and a derived **treated** table in the same Postgres database, harmonizes the cross-schema-version columns, reuses the existing dedupe/treatment/targets code, flags one canonical row per incident, and emits a machine-readable cleaning manifest the site can render.

---

## Problem Frame

This is **Phase 1** of the NHTSA AV crash project (see origin: `docs/brainstorms/nhtsa-crash-project-requirements.md`). The Railway Postgres and site are stood up; what's missing is the data. Today the data lives only as two CSVs (`data/nhtsa/`) and is loaded ad-hoc inside notebooks via `eda_utils_sgo.load_and_concat_csvs`. The two files are **schema versions of one dataset** — 2295×137 (early) and 825×116 (later), with ~52 columns only in early, ~27 only in later, and several documented analogue pairs that use different formats across versions. Cleaning, dedupe, and target logic already exist as `eda/eda_utils_*.py` modules but (a) run only in notebooks, (b) *drop* duplicate incident reports rather than flagging them, (c) don't harmonize the cross-version analogue columns, and (d) leave no durable record of what cleaning was applied. This plan turns that notebook workflow into a repeatable load that the website can query, and makes the cleaning process self-documenting.

---

## Requirements

- R1. (origin R10) NHTSA SGO data ingested into Postgres via a reproducible script; raw + cleaned tables both retained.
- R2. (origin R11) Cleaning pass handles known-messy fields; cleaning rules are documented (not just in code) via a machine-readable artifact the site can render.
- R3. (origin R12, partial) Cleaning manifest + column dictionary emitted as a single source of truth (JSON in repo) for the future data-dictionary page. *Site-side rendering is out of scope here.*
- R4. Re-ingestion is safe and versioned: monthly file refreshes keep history; the website pulls the newest version.
- R5. Treated layer exposes one canonical row per incident via a single boolean flag, without losing the non-canonical rows.
- R6. Cross-schema-version analogue columns (engagement, belted, weather, roadway, lighting) are harmonized into common cleaned columns, extending the airbag/towed cross-version pattern already in `eda/eda_utils_targets.py`.

**Origin actors:** self (data scientist / site owner); anonymous site visitor (downstream consumer of treated table + manifest).
**Origin flows:** monthly batch refresh → ingest raw → rebuild treated → emit manifest → site reads newest.

---

## Scope Boundaries

- No frontend/site code. This plan produces the treated table and the manifest artifact; rendering the data-dictionary page lives in the site repo.
- No real-time/streaming ingest — periodic batch only (origin scope).
- No new modeling or EDA analysis; targets are carried over as-is from `eda/eda_utils_targets.py`.
- No re-identification or PII enrichment beyond what NHTSA redacts (origin scope).
- No rewrite of existing dedupe/treatment/targets logic beyond the non-destructive flag refactor.

### Deferred to Follow-Up Work

- Data-dictionary **field-meaning** extraction from `data/nhtsa/SGO-2021-01_Data_Element_Definitions.pdf`: separate effort; this plan's column dictionary lists columns + provenance, not regulatory field definitions.
- Mirroring the cleaning manifest into a queryable DB table (`cleaning_steps`): JSON-in-repo is the source of truth for v1; a DB mirror can follow if the site prefers SQL over reading the file.
- Alembic / migration framework: deferred until schema churn justifies it.
- FastAPI endpoints that serve the treated data: site-repo work.

---

## Context & Research

### Relevant Code and Patterns

- `eda/eda_utils_sgo.py` — `load_and_concat_csvs(paths)` already concatenates the two CSVs into a column-union frame and prints schema diffs + dtype mismatches (`Model Year`, `SV Precrash Speed (MPH)`). Reuse as the superset-frame builder.
- `eda/eda_utils_dedupe.py` — `dedupe_same_incident(df)` computes incident grouping (`Same Incident ID`, else fallback key `Reporting Entity`+`Incident Date`+`Incident Time (24:00)`+`VIN`) and recency ordering (`Report Submission Date`, `Report Version`, `Report ID` desc), then **collapses** to one row + a merged `Narrative - Same Incident ID`. Refactor target for U4: emit the flag instead of dropping.
- `eda/eda_utils_treatment.py` — `apply_all_treatments(df)` appends cleaned org/state columns, `master_entity`, `Make Model`. Reuse unchanged.
- `eda/eda_utils_targets.py` — `add_all_targets(df)` appends 7 targets; `AIRBAG_COLS`/`TOWED_COLS` already unify the cross-version airbag/towed fields via case-insensitive "yes" substring matching. This is the exact pattern U5 extends to engagement/belted/weather/roadway.
- `eda/ADS_to_2026_03_16/06_eda_clean_up_summary.ipynb` — documents the analogue column pairs and the explicit TODO (`is_latest_of_multiple_report`, orchestration, step listing). Source of the harmonization value sets used in U5.
- `eda/tests/conftest.py` — test convention: adds `eda/` to `sys.path` so `eda_utils_*` import by bare name. New `eda/tests/test_*.py` files follow this; pipeline code mirrors the same `sys.path` insertion to import treatment modules.
- `.gitignore` already excludes `.env` — DATABASE_URL goes there, never committed.

### Institutional Learnings

- `docs/solutions/` — none directly applicable to DB ingestion; this plan establishes the first ingest pattern. Worth a `ce-compound` writeup after landing.

### External References

- pandas `DataFrame.to_sql` with a SQLAlchemy engine is the idiomatic load path for this scale (~3,120 raw rows × ~150 cols); no need for COPY or bulk tooling yet.
- psycopg (v3) + SQLAlchemy 2.x is the current Postgres stack for Railway-hosted Postgres via `DATABASE_URL`.

---

## Key Technical Decisions

- **Raw stored as a single superset table, all columns TEXT.** Union of both schema versions; missing columns NULL per row. Storing raw as TEXT preserves source fidelity and side-steps the known dtype mismatches (`Model Year` float/int, speed float/int); typing happens only in the treated layer. Rationale: it's one dataset, not two; avoids UNIONs forever; future months just append.
- **`schema_version` + `source_file` columns** distinguish early vs later rows in the one table.
- **Append-only raw + `ingest_batches` metadata table + a `raw_incident_reports_latest` view.** Each load is a batch (`batch_id`, `source_file`, `sha256`, `row_count`, `ingested_at`). The view selects the most-recent batch per natural key so the site "pulls newest" with no client-side logic. Rationale: keeps full history, makes monthly refresh reproducible and auditable. (Upsert-on-natural-key was the alternative — rejected to preserve history.)
- **Natural key = (`Report ID`, `Report Version`); incident grouping = `Same Incident ID` + fallback key.** Reuses the grouping rules already encoded in `eda_utils_dedupe.py`.
- **Treated data in the same database, separate table** (`treated_incident_reports`). One connection, joinable back to raw. (Separate Postgres database rejected — cross-DB joins are painful on Railway.)
- **Treated table is fully rebuilt each run** from the raw `latest` view (derived data, cheap at this scale), carrying a `source_batch_ids` / `built_at` provenance stamp.
- **`is_latest_of_multiple_report` is a canonical-row flag covering singletons** (true for the latest row of a multi-report group AND for standalone single-report incidents) plus a separate `has_multiple_reports` flag. The site filters one boolean for one-row-per-incident.
- **DB access via SQLAlchemy engine + pandas `to_sql`, plain SQL DDL files, no migration framework.** Connection from `DATABASE_URL`.
- **Unknown columns fail loud.** If an incoming CSV has a column not in the raw table, ingest aborts the batch (names the offending columns, writes nothing) rather than silently dropping or auto-adding. Schema growth is a deliberate act — extend the DDL and re-run.
- **Guarded `--reset` (drop + recreate) + transactional ingest** for safe iteration on Railway. `--reset` drops and recreates all tables/views; it is destructive and must be explicitly requested. Each ingest commits its appended rows and its `ingest_batches` row in one transaction, so a failed/partial run rolls back cleanly. Together with the `sha256` guard (a re-run of the same file inserts 0 rows by default), repeated test runs never accumulate duplicate data.
- **Cleaning docs are generated, not hand-written.** The pipeline emits `docs/data-dictionary/cleaning_manifest.json` (ordered steps: name, inputs, output, rule, before/after stats) and `docs/data-dictionary/column_dictionary.json` (every treated column + provenance) as the single source of truth.
- **Code location:** new top-level `db/` package for connection/schema/ingest/orchestration; treatment-side logic (flag refactor, harmonization, manifest assembly helpers) stays in `eda/eda_utils_*.py` per the repo's flat-module convention.

---

## Open Questions

### Resolved During Planning

- Raw storage shape → single superset table (user confirmed).
- Treated layer location → same DB, separate table (user confirmed).
- Where Postgres lives / where code lives → Railway DB exists; code in this repo via `DATABASE_URL` (user confirmed).
- `is_latest_of_multiple_report` semantics → canonical-row flag covering singletons + `has_multiple_reports` (user confirmed).
- Re-ingestion model → append-only + batch + latest view (user confirmed).
- Cleaning docs → generated manifest (user confirmed).
- Migration tooling → no Alembic yet (user confirmed).
- Unknown/new columns in a future file → **fail loud** (abort batch, name columns, write nothing); schema growth is a deliberate DDL change (user confirmed).
- Reset/teardown → add a guarded `--reset` (drop + recreate) now for Railway iteration; pair with transactional ingest + the `sha256` guard so re-runs never double-insert (user confirmed).

### Deferred to Implementation

- Exact harmonization value maps for engagement/belted/weather/roadway: source value sets are enumerated in U5; final mapping is fixed when running `value_counts` on the full combined frame.
- Whether treated rebuild truncates-in-place or writes-then-swaps: decide when measuring `to_sql` time on the real table.
- Promoting a few high-value raw columns to typed columns (dates, lat/long, speed) in the treated layer — decide per column during U6.

---

## Output Structure

    db/
      __init__.py
      connection.py            # SQLAlchemy engine from DATABASE_URL, ping helper
      sql/
        001_raw_incident_reports.sql
        002_ingest_batches.sql
        003_treated_incident_reports.sql
        004_raw_latest_view.sql
        099_drop_all.sql         # teardown for guarded --reset
      create_tables.py         # idempotent DDL runner (create-if-not-exists) + reset()
      ingest_raw.py            # CSVs -> superset frame -> append + batch record
      build_treated.py         # raw latest -> treatment pipeline -> treated table
      manifest.py              # assemble + write cleaning_manifest / column_dictionary
      run_pipeline.py          # CLI: create -> ingest -> build -> emit
      tests/
        __init__.py
        conftest.py
        test_create_tables.py
        test_ingest_raw.py
        test_build_treated.py
        test_manifest.py
    eda/
      eda_utils_dedupe.py      # MODIFY: add canonical-row flag (non-destructive)
      eda_utils_harmonize.py   # NEW: cross-version analogue harmonization
      tests/
        test_eda_utils_dedupe.py    # NEW
        test_eda_utils_harmonize.py # NEW
    docs/data-dictionary/
      cleaning_manifest.json   # generated
      column_dictionary.json   # generated

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
data/nhtsa/*.csv ─┐
                  ▼
        ingest_raw.py ──► raw_incident_reports (append, all TEXT, +schema_version,
                  │         +source_file, +ingest_batch_id, +ingested_at)
                  └──► ingest_batches (batch_id, source_file, sha256, row_count, ingested_at)
                              │
                  raw_incident_reports_latest (view: newest batch per Report ID+Version)
                              ▼
        build_treated.py:
            dedupe flag (eda_utils_dedupe)  ──► is_latest_of_multiple_report, has_multiple_reports,
                                                Narrative - Same Incident ID
            apply_all_treatments (eda_utils_treatment) ──► *Clean cols, master_entity, Make Model
            harmonize (eda_utils_harmonize) ──► engagement/belted/weather/roadway/lighting_clean
            add_all_targets (eda_utils_targets) ──► 7 target columns
                              ▼
                  treated_incident_reports (typed where useful, +source_batch_ids, +built_at)
                              │
        manifest.py ──► docs/data-dictionary/cleaning_manifest.json
                        docs/data-dictionary/column_dictionary.json
```

Orchestrated end-to-end by `run_pipeline.py` (create → ingest → build → emit), each stage idempotent.

---

## Implementation Units

### U1. DB connection module + env wiring

**Goal:** A SQLAlchemy engine built from `DATABASE_URL`, plus a `ping()` that verifies connectivity with a trivial query.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `db/__init__.py`, `db/connection.py`
- Create: `db/tests/__init__.py`, `db/tests/conftest.py`, `db/tests/test_create_tables.py` (engine/ping portion)
- Modify: env handling — document `DATABASE_URL` in `.env` (already gitignored)

**Approach:**
- `get_engine()` reads `DATABASE_URL`; raise a clear error if unset.
- `ping()` runs `SELECT 1`; used by the pipeline preflight (origin R7's "verified end-to-end with one trivial query" pattern).
- Add `sqlalchemy` and `psycopg[binary]` to the uv env requirements (see `eda/ADS_to_2026_03_16/EDA_README.md` for env-update steps).

**Patterns to follow:** Mirror `eda/tests/conftest.py` `sys.path` insertion so `db/` tests and pipeline can import `eda_utils_*`.

**Test scenarios:**
- Happy path: `get_engine()` returns an engine when `DATABASE_URL` is set (use a sqlite URL in tests to avoid a live Postgres).
- Error path: `get_engine()` raises a descriptive error when `DATABASE_URL` is unset.
- Happy path: `ping()` returns truthy against an in-memory sqlite engine.

**Verification:** Running the preflight against the real Railway DB prints a successful `SELECT 1`.

---

### U2. Schema DDL + idempotent table creation

**Goal:** DDL for `raw_incident_reports` (superset, TEXT + metadata), `ingest_batches`, `treated_incident_reports`, and the `raw_incident_reports_latest` view; an idempotent runner that creates them if absent.

**Requirements:** R1, R4

**Dependencies:** U1

**Files:**
- Create: `db/sql/001_raw_incident_reports.sql`, `db/sql/002_ingest_batches.sql`, `db/sql/003_treated_incident_reports.sql`, `db/sql/004_raw_latest_view.sql`, `db/sql/099_drop_all.sql`
- Create: `db/create_tables.py`
- Test: `db/tests/test_create_tables.py`

**Approach:**
- Raw table: every source column as nullable TEXT, named to match CSV headers (kept quoted/stable). Metadata columns: `ingest_batch_id`, `source_file`, `schema_version`, `ingested_at`.
- Column set sourced from the union of both CSV headers (the early/later column lists in `06_eda_clean_up_summary.ipynb` are the reference) — generate the column list programmatically from the CSV headers at creation to avoid hand-maintaining ~165 names.
- `ingest_batches`: `batch_id` PK, `source_file`, `sha256`, `row_count`, `schema_version`, `ingested_at`, `notes`.
- `raw_incident_reports_latest` view: most-recent `ingest_batch_id` per (`Report ID`, `Report Version`).
- `create_tables.py` exposes `create()` (`CREATE TABLE IF NOT EXISTS` / `CREATE OR REPLACE VIEW`, safe to re-run) and `reset()` (runs `099_drop_all.sql` then `create()`). `reset()` is destructive — only invoked behind the explicit `--reset` flag (U8), never as part of a default run.

**Technical design:** *(directional)* treated table carries typed columns where useful (`incident_date DATE`, `latitude/longitude NUMERIC`, `sv_precrash_speed_mph NUMERIC`), the flag columns (`is_latest_of_multiple_report BOOLEAN`, `has_multiple_reports BOOLEAN`), the 7 target columns, the `*_clean` and harmonized columns, and provenance (`source_batch_ids`, `built_at`).

**Patterns to follow:** Plain SQL files executed via SQLAlchemy; no ORM models.

**Test scenarios:**
- Happy path: running `create_tables` twice against sqlite leaves the schema unchanged (idempotent, no error on second run).
- Happy path: all four objects exist after creation (introspect table/view names).
- Edge case: the generated raw column list equals the union of both CSV headers (no dropped/duplicated columns).
- Happy path: `reset()` on a populated DB drops then recreates — tables exist afterward and `raw_incident_reports` is empty.

**Verification:** Tables and view present in the Railway DB; re-running `create()` is a no-op; `reset()` returns a clean, empty schema.

---

### U3. Raw ingestion (superset frame → append + batch record)

**Goal:** Load the two CSVs into the superset frame, tag `schema_version`/`source_file`, append to `raw_incident_reports`, and record an `ingest_batches` row. Guard against accidental double-ingest of an identical file.

**Requirements:** R1, R4

**Dependencies:** U2

**Files:**
- Create: `db/ingest_raw.py`
- Test: `db/tests/test_ingest_raw.py`
- Reuse: `eda/eda_utils_sgo.py` (`load_and_concat_csvs`)

**Approach:**
- Per file: read CSV, compute `sha256`, tag `source_file` + `schema_version` (early/later), assign a new `batch_id`.
- Build the superset frame via column-union alignment (pandas reindex to the raw table's full column set; missing → NULL); cast all values to string for the TEXT raw table, mapping blanks/NaN to SQL NULL.
- Append via `to_sql(..., if_exists='append')` and write the `ingest_batches` row **inside one transaction** — if either fails, the whole batch rolls back (no orphan rows, no half-written batch).
- Double-ingest guard: if an `ingest_batches` row with the same `sha256` exists, skip and warn unless `--force`.
- Unknown columns **fail loud**: before appending, diff the incoming columns against the raw table's columns; if any incoming column is absent from the table, abort the batch, name the offending columns, and write nothing. Extending the schema is a deliberate DDL edit, not an automatic side effect of ingest.

**Patterns to follow:** `load_and_concat_csvs` already reports schema/dtype diffs — reuse its column-diff output for the batch `notes`.

**Test scenarios:**
- Happy path: ingesting both sample CSVs appends `2295 + 825 = 3120` rows and writes 2 batch rows with correct `row_count` and `schema_version`.
- Edge case: a row present only in the early schema has NULLs for later-only columns (e.g., `Engagement Status`) and vice versa.
- Error/guard path: re-ingesting the same file (same `sha256`) without `--force` appends 0 rows and logs a skip.
- Error path (fail loud): a CSV containing a column not present in the raw table aborts the batch, names the column, and writes 0 rows + 0 batch records.
- Error path (transactional): a simulated failure after the row append but before the batch row commits leaves the table unchanged (full rollback — no orphan rows).
- Edge case: empty-string and whitespace-only source cells land as SQL NULL, not `''`.
- Integration: after ingest, `raw_incident_reports_latest` returns one row per (`Report ID`, `Report Version`) from the newest batch.

**Verification:** Row counts in `raw_incident_reports` and `ingest_batches` match expectations; re-run is a safe no-op.

---

### U4. Canonical-row flag refactor in `eda_utils_dedupe`

**Goal:** Add a non-destructive function that returns the input frame plus `is_latest_of_multiple_report` (canonical, covers singletons), `has_multiple_reports`, and the merged `Narrative - Same Incident ID` — without dropping rows. Leave `dedupe_same_incident` intact.

**Requirements:** R5

**Dependencies:** None (pure pandas; can land in parallel with U1–U3)

**Files:**
- Modify: `eda/eda_utils_dedupe.py` (add `flag_incident_reports(df, ...)`; reuse `_build_group_keys`, `_RECENCY_COLS`, `_join_unique`)
- Test: `eda/tests/test_eda_utils_dedupe.py` (new)

**Approach:**
- Reuse the existing grouping (`_build_group_keys`) and recency ordering.
- Within each group, mark the most-recent row `is_latest_of_multiple_report = True`; all others False. Standalone/`UNIQUE` groups (size 1) → True (they ARE the one row for that incident).
- `has_multiple_reports = group_size > 1`.
- Attach the merged-narrative string to the canonical row only (mirrors the existing `narrative_out` behavior), leaving non-canonical rows' merged-narrative NULL.
- Function returns the full frame (same row count as input), index-aligned.

**Execution note:** Refactor with characterization in mind — assert the new flag, when filtered to True, reproduces the row count and key fields of today's `dedupe_same_incident` output on the same input.

**Patterns to follow:** `dedupe_same_incident` grouping/recency/`_join_unique` logic.

**Test scenarios:**
- Happy path: a 2-report group (same `Same Incident ID`) yields exactly one `is_latest_of_multiple_report=True` row = the highest `Report Submission Date`/`Report Version`/`Report ID`.
- Edge case: a single-report incident (no `Same Incident ID`, unique fallback key) → `is_latest_of_multiple_report=True`, `has_multiple_reports=False`.
- Edge case: blank/whitespace `Same Incident ID` falls back to the composite key; a fully-missing fallback component → standalone (True/False).
- Characterization: on the combined sample frame, `df[flag].sum()` equals `len(dedupe_same_incident(df))` — i.e., 2344 canonical rows from 3120 input rows.
- Edge case: merged narrative present on the canonical row, NULL on non-canonical rows; exact-duplicate narratives are not repeated.

**Verification:** Filtering treated rows on `is_latest_of_multiple_report` returns 2344 rows on the current data; input row count is preserved (no drops).

---

### U5. Cross-version analogue column harmonization

**Goal:** New module mapping early- and later-schema analogue fields to common cleaned columns, extending the airbag/towed cross-version pattern.

**Requirements:** R6

**Dependencies:** None (pure pandas; parallel with U1–U4)

**Files:**
- Create: `eda/eda_utils_harmonize.py` (`harmonize_all(df)` + per-field `harmonize_*` helpers)
- Test: `eda/tests/test_eda_utils_harmonize.py`

**Approach:** Add a `*_clean` column per analogue family; keep raw columns intact. Source value sets (from `06_eda_clean_up_summary.ipynb`):
- **Engagement** → `automation_engaged_clean` {Engaged, Not Engaged, Unknown} (+ `automation_system_type` {ADS, ADAS, Unknown} where derivable). Early `Automation System Engaged?`: ADS→Engaged, ADAS→system_type ADAS, "Unknown, see Narrative"→Unknown. Later `Engagement Status`: Verified Engaged/Alleged Engaged→Engaged, Verified Not Engaged→Not Engaged, Unknown→Unknown. *Note the semantic mismatch (early encodes system type, later encodes engagement state) — document it in the manifest.*
- **Belted** → `passengers_belted_clean` {All Belted, No Passengers, Not Belted, Unknown}. Early `SV Were All Passengers Belted?` (Yes / No Passengers in Vehicle / No, see Narrative / Unknown) ↔ later `Were All Passengers Belted?` (Subject Vehicle - All Belted / No Passenger In Vehicle / Not Belted - see Narrative / Unknown).
- **Weather** → normalized weather flags with a shared vocabulary: map `Weather - Fog/Smoke` ↔ `Weather - Fog/Smoke/Haze`, fold `Partly Cloudy`→Cloudy, unify `Unknown`/`Unk - See Narrative`; keep later-only categories (Dust Storm, Severe Hurricane, Structure-Indoor) as their own flags present-only-in-later.
- **Roadway** → harmonize early `Roadway Surface`/`Roadway Description` against later `Roadway-*` booleans into common condition flags where they correspond (wet surface, work zone, degraded marking); keep shared `Roadway Type` as-is.
- **Lighting** → early-only `Lighting` (Daylight / Dark - Lighted / Dawn-Dusk / Dark - Not Lighted / Unknown / Dark - Unknown Lighting / Other). No later analogue — carry through and flag as early-only in the manifest.

**Patterns to follow:** `eda/eda_utils_targets.py` `_contains_yes` / `AIRBAG_COLS` cross-version union; `_safe_col` for missing-column tolerance.

**Test scenarios:**
- Happy path (engagement): early "ADS" → Engaged; later "Verified Engaged" → Engaged; later "Verified Not Engaged" → Not Engaged.
- Happy path (belted): early "Yes" and later "Subject Vehicle - All Belted" both → All Belted; early "No Passengers in Vehicle" and later "No Passenger In Vehicle" both → No Passengers.
- Edge case: a row from the early schema (no `Engagement Status` column) still harmonizes from `Automation System Engaged?`, and a later-schema row (no `Automation System Engaged?`) harmonizes from `Engagement Status` — column-missing tolerance via `_safe_col`.
- Edge case (weather): `Weather - Fog/Smoke` (early) and `Weather - Fog/Smoke/Haze` (later) map to the same normalized flag.
- Edge case (lighting): later-schema rows get NULL/Unknown for `lighting_clean` (no source column) and the manifest records it as early-only.
- Happy path: `harmonize_all` is safe on a frame missing any given source column (no exception).

**Verification:** On the combined frame, each `*_clean` column's value counts reconcile with the summed source value counts shown in `06_eda_clean_up_summary.ipynb`.

---

### U6. Treated-frame builder + treated table load

**Goal:** Orchestrate the treatment pipeline over the raw `latest` view and write `treated_incident_reports`.

**Requirements:** R1, R2, R5, R6

**Dependencies:** U2, U3, U4, U5

**Files:**
- Create: `db/build_treated.py`
- Test: `db/tests/test_build_treated.py`
- Reuse: `eda/eda_utils_treatment.py` (`apply_all_treatments`), `eda/eda_utils_targets.py` (`add_all_targets`)

**Approach:**
- Read `raw_incident_reports_latest` into a DataFrame; coerce the handful of promoted columns to real types (dates, numeric lat/long/speed) for the typed treated columns.
- Pipeline order: `flag_incident_reports` (U4) → `apply_all_treatments` → `harmonize_all` (U5) → `add_all_targets`. Record per-step row/column deltas for the manifest (U7).
- Write the full frame (all rows, flag-distinguished — not collapsed) to `treated_incident_reports` with `to_sql(if_exists='replace')` or truncate+append; stamp `source_batch_ids` and `built_at`.
- Treated keeps both raw-passthrough and derived columns so the site can join/filter without touching raw.

**Patterns to follow:** The notebook preamble in `06_eda_clean_up_summary.ipynb` cell `cell-11` is the exact call sequence (dedupe → treatments), extended with harmonize + targets + flag-instead-of-collapse.

**Test scenarios:**
- Happy path: treated row count equals raw-latest row count (no drops); `is_latest_of_multiple_report=True` subset = 2344 on current data.
- Happy path: all 7 target columns, all `*_clean` columns, `master_entity`, `Make Model`, and the flag columns are present in the treated table.
- Integration: a known incident with 3 reports appears as 3 treated rows, exactly one flagged canonical, with the merged narrative on the canonical row.
- Edge case: rebuild is idempotent — running the build twice yields identical treated contents (replace semantics).
- Error path: build aborts with a clear message if `raw_incident_reports_latest` is empty.

**Verification:** Treated table populated; canonical-filtered query returns one row per incident with cleaned + target + harmonized columns.

---

### U7. Cleaning manifest + column dictionary emission

**Goal:** Emit machine-readable artifacts documenting every cleaning step and every treated column, as the single source of truth for the future data-dictionary page.

**Requirements:** R2, R3

**Dependencies:** U6

**Files:**
- Create: `db/manifest.py`
- Create (generated output): `docs/data-dictionary/cleaning_manifest.json`, `docs/data-dictionary/column_dictionary.json`
- Test: `db/tests/test_manifest.py`

**Approach:**
- `cleaning_manifest.json`: ordered list of steps, each `{step, description, input_columns, output_columns, rule_summary, rows_in, rows_affected}` — populated from the per-step deltas captured in U6 (dedupe-flag, org/state normalization, master entity, make+model, each harmonization family, each target).
- `column_dictionary.json`: one entry per treated column `{name, source_type: raw|cleaned|harmonized|target|flag|provenance, derived_from, description, sql_type}`.
- Include the semantic caveats surfaced in U5 (engagement system-vs-state mismatch; lighting early-only).
- Stamp `generated_at` and the `source_batch_ids` so the artifact is traceable to a specific load.

**Patterns to follow:** Treat the existing function docstrings in `eda_utils_treatment.py` / `eda_utils_targets.py` as the seed `rule_summary` text so docs stay close to code.

**Test scenarios:**
- Happy path: manifest contains one entry per pipeline step in execution order; each names ≥1 output column.
- Happy path: every column in `treated_incident_reports` has a `column_dictionary.json` entry (no orphan columns).
- Edge case: target columns are tagged `source_type: target`; flag columns `flag`; `*_clean` columns `harmonized`/`cleaned`.
- Happy path: emitted JSON is valid and re-loadable; `generated_at` and `source_batch_ids` present.

**Verification:** Both JSON files written under `docs/data-dictionary/`, valid JSON, columns reconcile 1:1 with the treated table.

---

### U8. End-to-end pipeline orchestration (CLI)

**Goal:** A single reproducible entrypoint: preflight → create tables → ingest raw → build treated → emit manifest, each stage idempotent and individually runnable.

**Requirements:** R1, R2, R4

**Dependencies:** U1–U7

**Files:**
- Create: `db/run_pipeline.py`
- Test: covered by stage tests; add a thin smoke test if a sqlite end-to-end is feasible
- Modify: a short `db/README.md` documenting env setup and run commands (and link from `eda/CLAUDE.MD` or repo root)

**Approach:**
- CLI flags: `--create-only`, `--ingest-only`, `--build-only`, `--emit-only`, `--force` (re-ingest same file), `--reset` (drop + recreate before running), default = full run.
- `--reset` is destructive: require an explicit confirmation prompt (or a paired `--yes` flag for non-interactive use) before dropping, and refuse silently-destructive runs.
- Preflight calls `connection.ping()`; fail fast with a clear message if `DATABASE_URL` is missing/unreachable.
- Print a concise run summary (rows ingested per batch, treated row count, canonical count, manifest paths).

**Patterns to follow:** Keep orchestration thin — it sequences U2–U7 functions, no business logic of its own.

**Test scenarios:**
- Happy path: full run against a local/sqlite target executes all stages in order and prints the summary.
- Edge case: `--build-only` on an already-ingested DB rebuilds treated without re-ingesting.
- Error path: missing `DATABASE_URL` aborts at preflight with a clear message before any write.
- Error path: `--reset` without confirmation (`--yes` absent in non-interactive mode) refuses to drop and exits non-zero.
- Integration: full run is idempotent — a second full run (no new file) ingests 0 new rows and leaves treated/manifest equivalent.
- Integration: `--reset` full run on a populated DB drops, recreates, and re-ingests to the same row counts (clean slate, no accumulation).

**Verification:** `python db/run_pipeline.py` against the Railway DB produces populated raw + treated tables and the two manifest files; documented in `db/README.md`.

---

## System-Wide Impact

- **Interaction graph:** The `treated_incident_reports` schema is the contract the FastAPI/site repo will query; column names (especially `is_latest_of_multiple_report`, the `*_clean` and target columns) are an external surface — name them deliberately and record them in `column_dictionary.json`.
- **External contracts:** `DATABASE_URL` env var (consumed here and by the site service); `docs/data-dictionary/*.json` (consumed by the future data-dictionary page).
- **Error propagation:** Preflight failures (no `DATABASE_URL`, unreachable DB) must abort before any write. Ingest guards against double-append via `sha256`.
- **State lifecycle risks:** Append-only raw can grow with repeated batches — the `latest` view, not raw row count, is what the site reads. Treated is rebuilt wholesale each run (no partial-write window if replace is transactional / swap-based).
- **Unchanged invariants:** `dedupe_same_incident` keeps its current drop-collapse behavior (notebooks still depend on it); the new flag function is additive. `apply_all_treatments` and `add_all_targets` are reused unmodified.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Future monthly file adds new columns not in the superset | **Fail loud**: ingest diffs incoming vs. table columns and aborts the batch (names the columns, writes nothing) so drift can't enter silently. Operator extends the DDL deliberately, then re-runs. |
| Accidental double-ingest inflates raw (esp. while testing on Railway) | Three layers: `ingest_batches.sha256` guard (re-run of same file = 0 rows unless `--force`); transactional ingest (failed run rolls back, no orphan rows); guarded `--reset` for a clean slate during iteration. |
| `--reset` accidentally drops production data | Destructive; requires explicit confirmation / `--yes`; never runs as part of a default invocation. |
| Engagement / weather analogues are not perfectly semantically equivalent across versions | Keep raw columns; document the mismatch explicitly in `cleaning_manifest.json`; harmonized columns are additive, not replacements. |
| `DATABASE_URL` secret leakage | Lives only in `.env` (already gitignored); never logged in full. |
| pandas NaN vs SQL NULL vs empty-string drift | Normalize blanks/whitespace → NULL on raw load (dedupe already treats blanks as NaN). |
| Treated rebuild contention while site reads | At this scale, replace is fast; if needed, write-then-swap (build into a temp table, rename) for an atomic cutover. |
| Dependency: `sqlalchemy` + `psycopg` not yet in the shared uv env | Add to env requirements per `EDA_README.md` as part of U1. |

---

## Alternative Approaches Considered

- **Two raw tables (old + new):** Rejected — they're one dataset; forces UNIONs and dual-schema awareness into every downstream query and the site.
- **Separate Postgres database for treated:** Rejected — cross-DB joins are painful on Railway; loses raw↔treated joinability for no isolation benefit a separate table doesn't already provide.
- **Upsert-on-natural-key for raw:** Rejected for v1 — append + batch + view preserves full history and makes monthly refreshes auditable; upsert discards prior versions.
- **Hand-written cleaning docs:** Rejected — drift from code; generating from the pipeline keeps docs truthful and feeds the data-dictionary page directly.
- **Alembic migrations:** Deferred — overkill at current schema churn; plain DDL files suffice.

---

## Documentation / Operational Notes

- Add `db/README.md`: env setup (`DATABASE_URL` in `.env`), uv env update (`sqlalchemy`, `psycopg`), and the four run modes.
- After landing, a `ce-compound` writeup on the ingest/treated pattern is worth capturing in `docs/solutions/` (first DB pattern in the repo).
- Monthly refresh runbook: drop the new CSV in `data/nhtsa/`, run `python db/run_pipeline.py`; the `latest` view exposes the newest version to the site automatically.

---

## Sources & References

- **Origin document:** [docs/brainstorms/nhtsa-crash-project-requirements.md](docs/brainstorms/nhtsa-crash-project-requirements.md) — Phase 1 (R10, R11, R12).
- Related code: `eda/eda_utils_sgo.py`, `eda/eda_utils_dedupe.py`, `eda/eda_utils_treatment.py`, `eda/eda_utils_targets.py`
- Reference notebook: `eda/ADS_to_2026_03_16/06_eda_clean_up_summary.ipynb`
- Data: `data/nhtsa/SGO-2021-01_Incident_Reports_ADS_to_2025_06_16.csv`, `data/nhtsa/SGO-2021-01_Incident_Reports_ADS_2025_06_16_to_2026_03_16.csv`
- Env setup: `eda/ADS_to_2026_03_16/EDA_README.md`, `eda/CLAUDE.MD`
