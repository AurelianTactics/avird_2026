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
  pagecache ≈128M.
  - **Provisioned 2026-07-06** (Neo4j 5.26.28 community on Railway, `avird-2026`
    project). Local dev / loader path: the public TCP proxy is **deleted between
    uses** (2026-07-08) — the old `hayabusa.proxy.rlwy.net:18523` address is dead.
    To run the loader/eval: recreate the proxy (Settings → Networking → TCP
    Proxy, port 7687), put the newly assigned `bolt://<host>:<port>` in the root
    `.env` + `apps/api/.env`, and delete the proxy after — **deleting
    `NEO4J_server_bolt_advertised__address` first** if it reappears (a dangling
    proxy reference crash-loops the next restart). Prod `api` uses the
    private-network URI on port 7687; that path needs
    `NEO4J_server_default__listen__address=::` on the service (IPv6-only private
    network — set 2026-07-08, keep it). Memory vars on the service:
    `NEO4J_server_memory_heap_max__size=512m`,
    `NEO4J_server_memory_pagecache_size=128m`. Credentials in the root `.env`
    and `apps/api/.env`. First load: 2,257 nodes / 3,153 relationships from
    `extract-20260618-154522-3ad34f17.jsonl`. Deploy sharp edges (crash-loop on
    `advertised_address ":"`, IPv6 listen address, requirements.txt drift): see
    the U13 runbook + 2026-07-08 postscript in
    `docs/writeups/kg-queries-nl-to-cypher.md`.
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
