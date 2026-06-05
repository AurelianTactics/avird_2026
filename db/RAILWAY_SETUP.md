# Railway setup — what you do, step by step

This is the **manual** side of running the pipeline against your Railway
Postgres for the first time. None of these steps can be automated from inside
this repo: they involve your Railway account, the secret connection string,
and verifying the result. Once they're done, monthly refreshes are one command
(see the bottom of this file).

> Prerequisites: you've cloned this branch, the uv env at
> `~/claude_code_repos/my-uv-envs/avird-2026-eda/` exists, and Railway already
> has a Postgres service provisioned for this project.

---

## 1. Grab the `DATABASE_URL` from Railway

1. Open <https://railway.app/> and sign in.
2. Open the project that hosts the AVIRD site.
3. Click the **Postgres** service tile.
4. Click the **Variables** tab.
5. Find `DATABASE_URL` (or `DATABASE_PUBLIC_URL` if you'll connect from your
   laptop rather than from inside Railway's network).
   - Use `DATABASE_PUBLIC_URL` from your laptop — the private one only
     resolves inside Railway.
6. Click the value to reveal it, then copy the whole string. It looks like:
   ```
   postgresql://postgres:<password>@<hostname>.proxy.rlwy.net:<port>/railway
   ```
   The `postgres://` and `postgresql://` schemes are both fine — `connection.py`
   rewrites them to use psycopg v3 automatically.

---

## 2. Put it in `.env` (gitignored)

1. At the repo root, create a file named `.env` (Windows: in PowerShell run
   `ni .env` if it doesn't exist).
2. Paste exactly:
   ```env
   DATABASE_URL=<paste the URL you copied>
   ```
3. Save. **Do not commit this file.** `.gitignore` already excludes it; verify
   with:
   ```bash
   git check-ignore -v .env
   ```
   That should print the matching `.gitignore` rule. If it prints nothing,
   stop and add `.env` to `.gitignore` first.

---

## 3. Activate the venv and install the new deps

The pipeline needs two new packages (`sqlalchemy` and `psycopg[binary]`) on
top of the existing env. They're already in `requirements.txt`; you just need
to install.

PowerShell:
```powershell
..\my-uv-envs\avird-2026-eda\.venv\Scripts\Activate.ps1
uv pip install -r ..\my-uv-envs\avird-2026-eda\requirements.txt
```

Bash (git-bash / WSL):
```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-eda/.venv/Scripts/activate
uv pip install -r ~/claude_code_repos/my-uv-envs/avird-2026-eda/requirements.txt
```

---

## 4. Preflight: verify connectivity

```bash
python db/run_pipeline.py --create-only
```

What you should see:
```
[run_pipeline] preflight OK (postgresql)
=== run_pipeline summary ===
stages: create
create: ok
```

If you see `DATABASE_URL is not set` instead, your `.env` isn't being loaded.
Confirm the file is at the repo root and the line is exactly
`DATABASE_URL=...` with no surrounding quotes.

If you see a connection error (`could not translate host name`, timeout,
ssl required) — re-check that you used `DATABASE_PUBLIC_URL`, and confirm the
service is up in the Railway dashboard.

---

## 5. Confirm the schema landed

In the Railway dashboard, click your Postgres service → **Data** tab. You
should see four objects:

- `raw_incident_reports` (table, 0 rows)
- `ingest_batches` (table, 0 rows)
- `treated_incident_reports` (table, 0 rows)
- `raw_incident_reports_latest` (view)

If you have `psql` or DBeaver handy, you can also run:
```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' ORDER BY table_name;
```

---

## 6. Run the full pipeline

```bash
python db/run_pipeline.py
```

Expected summary (numbers will match the current CSVs in `data/nhtsa/`):
```
=== run_pipeline summary ===
stages: create, ingest, build, emit
create: ok
ingest [early] SGO-2021-01_Incident_Reports_ADS_to_2025_06_16.csv: +2295 rows
ingest [later] SGO-2021-01_Incident_Reports_ADS_2025_06_16_to_2026_03_16.csv: +825 rows
build : 3120 treated rows (2344 canonical), 2 source batch(es)
manifest: docs/avird-sgo-database-data-dictionary/cleaning_manifest.json
columns : docs/avird-sgo-database-data-dictionary/column_dictionary.json
```

This takes ~30–60s the first time (CSV read + pipeline + Postgres write).

---

## 7. Spot-check the row counts in Railway

Open the Railway Postgres **Query** tab (or your local psql) and run:

```sql
SELECT COUNT(*) FROM raw_incident_reports;          -- expect 3120
SELECT COUNT(*) FROM ingest_batches;                -- expect 2
SELECT schema_version, COUNT(*)
  FROM raw_incident_reports
  GROUP BY schema_version;                          -- expect early=2295, later=825
SELECT COUNT(*) FROM raw_incident_reports_latest;   -- distinct natural keys
SELECT COUNT(*) FROM treated_incident_reports;      -- matches the view count
SELECT COUNT(*) FROM treated_incident_reports
  WHERE is_latest_of_multiple_report = TRUE;        -- expect 2344
```

If any of those don't match, **stop** and tell me — something's off.

---

## 8. Verify the manifest files

Two JSON files are written to `docs/avird-sgo-database-data-dictionary/`:

```bash
ls docs/avird-sgo-database-data-dictionary/
# cleaning_manifest.json   column_dictionary.json
```

Open both and confirm:
- `cleaning_manifest.json` has 9 entries under `steps` (promote_typed_columns,
  dedupe_flag, treatments, harmonize_engagement, harmonize_belted,
  harmonize_weather, harmonize_roadway, harmonize_lighting, targets).
- `column_dictionary.json` has one entry per treated column with a
  `source_type` of `raw`, `cleaned`, `harmonized`, `target`, `flag`, or
  `provenance`.

These files are commit-tracked — they're the contract the site reads to
render the data-dictionary page.

---

## Monthly refresh (after the first run)

Each month NHTSA publishes a new SGO CSV. The workflow:

1. Drop the new file into `data/nhtsa/`.
2. Re-run:
   ```bash
   python db/run_pipeline.py
   ```
3. The sha256 guard skips files already ingested; the new one appends as a
   new batch. The `raw_incident_reports_latest` view automatically exposes
   the newest rows to the site. The treated table and manifest are rebuilt.
4. Commit the regenerated `docs/avird-sgo-database-data-dictionary/*.json` if any column changed.

---

## When you want a clean slate (rare)

If the schema drifts or you want to reset the Railway DB while iterating:

```bash
python db/run_pipeline.py --reset --yes
```

This DROPS every table + view and recreates them, then runs the full
pipeline. **Destructive.** Refuses to run in non-interactive shells without
the explicit `--yes`. Don't run this in prod once the site is live.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `DATABASE_URL is not set` | `.env` missing or has the wrong key | Recreate `.env` at the repo root, exact key `DATABASE_URL` |
| `could not translate host name` | Used `DATABASE_URL` (private) from laptop | Use `DATABASE_PUBLIC_URL` from Railway instead |
| `SSL connection required` | Railway needs SSL | Add `?sslmode=require` to the URL |
| `psycopg.errors.UndefinedColumn` after a new CSV | NHTSA added a column | Extend `db/sql/001_raw_incident_reports.sql` — the pipeline aborts the batch by design when an unknown column appears; the error names the new columns |
| Pipeline ingests but adds 0 rows | Same sha256 already loaded | Intentional sha256 guard; pass `--force` if you really want to re-ingest |

---

If anything in steps 4–8 doesn't match the expected output, paste the
terminal output back to me and I'll diagnose. The pipeline is fully sqlite-tested
locally; what's left to verify is the Railway-specific shape of your DB
(network, SSL, schema permissions).
