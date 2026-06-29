# Fault judge (offline batch)

Precompute track for the **LLM fault judge** (Feature 1 of the fault plan). A
neutral "insurance adjuster" LLM reads each incident's narrative + key
structured fields and writes one structured verdict per
`(report_id, fault_version)` into the `fault_analysis` table. The `api` then
surfaces those verdicts read-only — no LLM deps on the read path. This file is a
thin index; design rationale lives in the plan
([docs/plans/2026-06-25-001-feat-fault-judge-and-debate-plan.md](../docs/plans/2026-06-25-001-feat-fault-judge-and-debate-plan.md)).

The live debate (Feature 2) is **not** here — it runs in `apps/api/app/debate.py`.

## Running code

Reuses the ontology sidecar env (Python 3.12 — already pins `langgraph` +
`langchain-anthropic`); no third venv:

```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-ontology/.venv/Scripts/activate
```

Secrets come from the root `.env` (gitignored): `ANTHROPIC_API_KEY` for the
batch, `DATABASE_URL` for the read/write. Tests need neither (stubbed LLM +
sqlite, no network).

## Run order

```bash
python fault/judge_batch.py --dry-run                 # count spend, no writes
python fault/judge_batch.py --limit 5                 # eyeball 5 rows first
python fault/judge_batch.py --fault-version mvp_0.01  # full run (~3,120 rows)
```

Create the table first if it does not exist: `python db/run_pipeline.py`
(or whatever runs `db/create_tables.create`) — `005_fault_analysis.sql`.

## Module placement

Flat modules at the base of `fault/` (mirrors `ontology/`):
- `format.py` — treated row → adjuster prompt text (narrative + structured fields).
- `graph.py` — single-node LangGraph adjuster + the `FaultVerdict` schema.
- `judge_batch.py` — load rows → judge → validate → upsert; `--limit/--dry-run`.

Tests mirror module names in `tests/test_<module>.py`.

## Sharp edges

- **No ADS filter — every row is judged.** Expect inconsistent verdicts across
  multiple reporting rows of the *same* real-world crash; that is acceptable and
  handled by a UI disclaimer, not by deduping.
- **Idempotent on `(report_id, fault_version)`.** A re-run of the same version
  UPSERTs; a new version appends. Re-run after a data re-seed to verdict new
  rows (idempotent + cache-backed, so it only bills genuinely new rows).
- **LLM cache is content-addressed** (shared `ontology/llm.py`): key = sha256 of
  the fully rendered prompt + model id, one JSON file per call under
  `ontology/artifacts/cache/`. Any prompt change invalidates by content.
- **Parse/validation failures store an explicit error sentinel** (NULL verdict +
  NULL percentage + an error string), never a guessed value. Range and length
  are validated by `coerce_verdict` in the batch, not by schema constraints.
