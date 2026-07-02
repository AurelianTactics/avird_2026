# Ontology pipeline

Property-graph ontology over SGO crash narratives: schema induction (seed from
structured columns + LLM concept discovery), LangGraph extraction, Neo4j
projection (Railway CE), golden-dataset evaluation. This file is a thin index — read the
plan ([docs/plans/2026-06-11-001-feat-ontology-pipeline-plan.md](../docs/plans/2026-06-11-001-feat-ontology-pipeline-plan.md))
only when you need design rationale.

## Running code

Deps live in a dedicated `uv` sidecar env (Python 3.12 — LangGraph /
langchain-anthropic / neo4j pins):

```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-ontology/.venv/Scripts/activate
```

Secrets come from the root `.env` (gitignored): `ANTHROPIC_API_KEY`,
`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, plus `DATABASE_URL` for the
corpus loader. Tests need none of them (stubbed LLM + Neo4j, no network).

## Module placement

Pipeline stages are flat modules at the base of `ontology/` (`corpus.py`,
`discover.py`, `extract.py`, ...). Add behavior to the stage module it belongs
to; split a module only past ~1000 lines. Tests mirror module names in
`tests/test_<module>.py`.

## Run order

```bash
python ontology/run_pipeline.py --help          # stage flags, --limit, --dry-run
python ontology/seed_schema.py                  # 1. deterministic seed draft
python ontology/discover.py --dry-run           # 2. LLM concept discovery -> draft
#    human: edit draft, add competency questions, save schema/v001.yaml, commit
python ontology/extract.py --limit 5 --dry-run  # 3. extraction -> artifacts/
python ontology/graph_load.py                   # 4. project artifact into AuraDB
python ontology/golden.py --help                # 5. golden sampling / pre-label
python ontology/evaluate.py                     # 6. metrics -> results/
```

## Sharp edges

- **The graph lives on Railway Neo4j CE (P3 decision, 2026-07-02) and is
  rebuildable-not-authoritative.** The AuraDB Free plan (72h idle pause, idle
  deletion) is superseded — the Railway instance is always-on — but the
  discipline is unchanged: never treat the graph as the source of truth; the
  extraction JSONL under `artifacts/extractions/` is. Rebuild:
  `python ontology/graph_load.py --reset --yes` then a fresh load
  (`graph_load.py` reads `NEO4J_URI`/`NEO4J_USERNAME`/`NEO4J_PASSWORD` as-is —
  no code change; local dev points at the Railway TCP proxy, see
  [docs/conventions/stack.md](../docs/conventions/stack.md)). The artifacts are
  gitignored — they live in the `avird-2026-ontology-v001` checkout; copy them
  into the working tree before a rebuild. Instance tuning: heap ≈512M,
  pagecache ≈128M (record the actual values here after provisioning).
  - **TODO(human):** Railway Neo4j CE service not yet provisioned — see the
    U13 instructions in the P3 plan/writeup; put credentials in `.env`, record
    the memory settings + proxy address here.
- **LLM cache is content-addressed**: key = sha256 of the fully rendered
  prompt + model id, one JSON file per call under `artifacts/cache/`. Any
  prompt or schema change invalidates by content — re-runs after a change pay
  only for misses. Deleting the cache dir re-bills everything.
- **Frozen schemas are never edited in place.** Extraction refuses to load
  schemas from `schema/drafts/`; revisions create `schema/v002.yaml` and imply
  graph wipe-and-rebuild + golden label-mapping.
- **Held-out golden split is final-numbers-only**: `evaluate.py` refuses
  `golden/heldout.jsonl` without `--heldout`. Iterate prompts against the dev
  split only.
