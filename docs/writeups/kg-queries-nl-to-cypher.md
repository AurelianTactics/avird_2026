# Knowledge-graph queries: NL → Cypher (agentic data-access P3)

The third phase of the [agentic data-access progression](../plans/2026-06-30-001-feat-agentic-data-access-progression-plan.md): P1's execute-observe-repair loop transferred from SQL over Postgres to **Cypher over the Neo4j ontology graph** — the property graph extracted from SGO crash narratives against the frozen `ontology/schema/v001.yaml`.

## What shipped

An NL→Cypher agent (`app/kgquery/`), with the web surface planned up front this time (the P1/P2 lesson: both phases "deferred" the route and both shipped one after iteration):

```bash
# ask a question (real model when ANTHROPIC_API_KEY is set, else a canned stub)
python -m app.kgquery.cli "which companies had pedestrian incidents?"
# score against the competency-question golden set (answer-set F1)
python tools/eval_kgquery.py            # dev split
python tools/eval_kgquery.py --heldout  # final numbers only
```

The pieces, the same five-dimension story:

- **Validations** — the P3 twist: there is **no read-only credential**. Neo4j Community Edition has no role management, so the structural floor is the **read-access-mode transaction** — every graph touch in `app/kgquery` goes through `execute_query(routing_=READ)`, and the server rejects any write at runtime regardless of what the model emitted. On top: a **static validator** (`validate.py`, U14) that accepts exactly one statement, rejects write clauses (`CREATE`/`MERGE`/`DELETE`/`DETACH`/`SET`/`REMOVE`/`FOREACH`/`DROP`/`LOAD CSV`) with string literals stripped first, rejects `CALL` **wholesale** (procedures are where read-only guarantees leak), rejects backtick identifiers (the escape hatch around the token scan), checks every `:Label`/`:REL` token against the schema allow-list, and injects a `LIMIT`; then an **`EXPLAIN` dry-run** in read mode catches syntax with zero execution.
- **Prompts** — system prompt fixes the output contract (one read-only Cypher, no prose/fences), the vocabulary constraint (only schema labels/rels/patterns), the universal `name` property, and the refusal contract (`RETURN NULL LIMIT 0`).
- **Context** — a **graph card** (`graph_card.py`, U14) rendered from the frozen schema yaml with plain pyyaml (never importing ontology modules — the api stays free of the sidecar env): 29 node labels with typed properties, 41 relationship types, and all 120 connection patterns. The schema being small and enumerable is the whole point of the graph — the entire vocabulary fits in the prompt (~12.6K chars).
- **Self-validation loop** — `assemble → generate → validate → execute(READ) → repair` (`agent.py`, U15), bounded by `max_iterations` (3) + budget. Two P3-specific edges: **graph-unreachable is a first-class degrade** (`graph_available=false`, zero model calls, budget untouched — the graph is rebuildable-not-authoritative and never assumed live), and a valid-but-empty result gets one bounded reconsideration (wrong entity name? wrong direction?) before the empty answer is accepted.
- **Golden set** — `golden/kgquery/{dev,heldout}.jsonl` (U16) seeded directly from the schema's **18 competency questions** (12 dev / 6 held-out, plus 3 unanswerable rows expecting refusal), scored on **answer-set equivalence + row-set F1** against hand-written gold Cypher — both candidate and gold execute read-mode against the live graph and are compared by results, never by query text. Held-out refuses without `--heldout`; a test pins that every committed gold Cypher passes the real static gate.
- **Web delivery** — `POST /kgquery/ask` + `GET /kgquery/status` (`routes.py`, U17), a same-origin proxy (`/api/kgquery/ask`), and the `/kg` page ("Ask the graph"): question box, the Cypher the model wrote, the result table, the repair trace, the schema-card sidebar (labels / rel types / patterns), a **persistent "answers cover the extracted subgraph (n≈143)" banner**, and a friendly graph-down state. Its own durable budget (`budget.py`, `KGQUERY_DAILY_BUDGET_USD`, ledger `kgquery_spend`) with the per-call estimate **measured from the rendered graph card** rather than a copied constant — the KTD-5 caveat, third time, resolved differently.

## The SQL→Cypher transfer — what carried, what didn't

**Carried almost verbatim:** the graph shape (nodes and edges are line-for-line parallel to `nlsql/agent.py`), the injected `Protocol` seams (model + data, fakes for every test), the budget reserve/release around the paid call, the attempts trace, the refusal contract idea, LIMIT injection, EXPLAIN-before-execute, and the golden discipline (execution-result comparison, split hygiene, deterministic summaries).

**Changed shape:**

- **The safety floor moved from a credential to a transaction mode.** Postgres gave us a `SELECT`-only role — safety by *identity*. CE Neo4j has no roles, so safety is by *session semantics* (`routing_=READ`), which the server enforces per statement. The floor is equally hard but lives in the seam's code, so the contract "every execution path goes through read mode" is pinned by a test on the real seam with a stubbed driver.
- **No sqlglot equivalent.** SQL got an AST walk; for Cypher the validator is a keyword/token gate (string literals stripped, backticks refused) with EXPLAIN + the read-mode floor + a graph that simply lacks off-schema labels as the deeper layers. Less precise, honestly documented as such — defense-in-depth rather than a parser guarantee.
- **The allow-list flipped from generated to frozen.** P1's schema card is introspected from the live DB so it can't drift; P3's card comes from the *frozen* schema yaml, which is the stronger source here — the graph was built from that schema, and the frozen-schema discipline means it can't drift either.
- **Graph-down is a product state, not an error.** Postgres is assumed up (the site depends on it); the graph is a rebuildable projection, so unreachable is a rendered, tested degrade at every layer (agent result, both routes, the page banner) and never costs a model call.

## Infrastructure decision (2026-07-02): Neo4j CE on Railway

Replaces the AuraDB Free assumption. Aura Free's 72h idle pause / eventual deletion was the worst operational risk for a learning project touched in bursts; a small always-on CE container (~512M heap + volume, ~$2–5/mo) on the same platform as everything else removes it. Provisioning is one click via Railway's official template (see the runbook below) — Railway has no managed Neo4j the way it has Postgres, so template or not, what runs is the official `neo4j:5.x-community` Docker image. The `api` reaches it over Railway's private network; local dev uses the public TCP proxy (unencrypted bolt + strong password — accepted for a rebuildable graph of public NHTSA data; toggle the proxy off between sessions). `ontology/graph_load.py` needed **zero code changes** — it reads `NEO4J_URI`/`NEO4J_USERNAME`/`NEO4J_PASSWORD` as-is. Coverage honesty: the graph holds the ~143-incident extraction subgraph, so `/kg` answers will disagree with `/nlsql` counts — hence the persistent banner instead of pretending parity.

## Golden numbers

Dev split, first live run (2026-07-06, graph at 2,257 nodes / 3,153 relationships from the 2026-06-18 extraction):

| metric | value |
|--------|-------|
| accuracy (exact answer-set match) | 0.3333 |
| mean answer-set F1 | 0.5537 |
| refusal precision | 1.0 |
| mean iterations | 1.5714 |

Re-run: `python tools/eval_kgquery.py` (writes `tools/results/kgquery-eval-dev.{json,md}`; needs `NEO4J_*` + `ANTHROPIC_API_KEY` in the process env — the app never loads dotenv itself).

Gold-Cypher sanity check (per `golden/kgquery/README.md`): the extraction stores `is_subject_vehicle` as the **strings** `'true'`/`'false'`, not booleans — the four gold queries matching `{is_subject_vehicle: true}` returned empty/zero answers until adjusted to `'true'`/`'false'` (dev rows 3 and 11, held-out rows 1 and 6, fixed 2026-07-06). After the fix all 12 answerable dev queries return rows.

## U13 runbook — the human console steps (completed 2026-07-06)

1. Deploy Railway's official Neo4j template — <https://railway.com/deploy/neo4j-graph-database> — **into the existing `avird-2026` project** (same private network as `api`). It runs `neo4j:5.x-community` with a `/data` volume. At the prompts: `NEO4J_AUTH=neo4j/<strong-password>` (password **must be ≥ 8 chars** or startup aborts); leave `NEO4J_PLUGINS` empty (the validator rejects `CALL`, so APOC would be unused attack surface).
   - **Sharp edge (bit us on first deploy):** the template is *not* proxy-pre-wired — it sets `NEO4J_server_bolt_advertised__address=${{RAILWAY_TCP_PROXY_DOMAIN}}:${{RAILWAY_TCP_PROXY_PORT}}` but doesn't create the TCP proxy, so those resolve empty and Neo4j crash-loops with `Configured socket address ... ":" does not conform`. Fix: create the TCP proxy (Settings → Networking → TCP Proxy, application port 7687) *before* the first deploy, or just delete the `NEO4J_server_bolt_advertised__address` variable — direct `bolt://` connections (which is all we use) never read the advertised address.
2. Add the optional memory vars on the service: `NEO4J_server_memory_heap_max__size=512m`, `NEO4J_server_memory_pagecache_size=128m`. Note the TCP-proxy `<host>:<port>` Railway assigns.
3. Set in the root `.env` **and** `apps/api/.env`: `NEO4J_URI=bolt://<proxy-host>:<proxy-port>` (plain `bolt://` — the proxy doesn't terminate TLS), `NEO4J_USERNAME=neo4j`, `NEO4J_PASSWORD=…`.
4. Copy from the `avird-2026-ontology-v001` checkout: `ontology/artifacts/extractions/*.jsonl` **and** `ontology/artifacts/runs/*.summary.json` (the loader refuses an artifact without its run summary).
5. From the ontology sidecar env: `python ontology/graph_load.py` (add `--reset --yes` when re-running), then `--counts-only` to verify.
6. On the `api` Railway service: `NEO4J_URI=bolt://neo4j.railway.internal:7687` + the same credentials (and `KGQUERY_DAILY_BUDGET_USD` if not the `$2` default).
7. Verify end-to-end: restart the local stack, run `python -m app.kgquery.cli "which companies had pedestrian incidents?"`, load `/kg` — the unreachable banner should be gone.
8. Sanity-check the gold Cypher against the loaded subgraph (`golden/kgquery/README.md`), run `python tools/eval_kgquery.py`, and record the dev numbers in the *Golden numbers* section above. Fill the `TODO(human)` in `ontology/CLAUDE.md` with the proxy address + memory settings. Toggle the TCP proxy off at session end.

## Postscript — the 2026-07-08 prod incident (three layers deep)

The first prod deploy that actually *served* `/kg` (the api had crash-looped on an
unrelated `parents[4]` path bug until 2026-07-07) showed the graph-down banner
permanently. Three real, independent problems were stacked on top of each other,
in discovery order:

1. **Deleting the TCP proxy (instead of toggling it off) armed the
   advertised-address crash-loop** from the runbook's step-1 sharp edge: with the
   proxy gone, `NEO4J_server_bolt_advertised__address=${{RAILWAY_TCP_PROXY_*}}`
   resolves to `":"` on the next restart. Deleting that variable is now part of
   proxy teardown; the proxy stays deleted between loads and gets recreated (new
   host:port → update local `.env`) only when a rebuild/eval needs it.
2. **Neo4j listened on IPv4 only while Railway's private network is
   IPv6-only.** The image default (`0.0.0.0`) means
   `bolt://neo4j.railway.internal:7687` is refused even when Neo4j is healthy —
   the same `--host ::` lesson as the web/api Procfiles
   (`docs/solutions/tooling-decisions/railway-monorepo-deploy-gotchas-2026-05-05.md`).
   Fix: `NEO4J_server_default__listen__address=::` on the Neo4j service; startup
   log confirms with `Bolt enabled on [0:0:0:0:0:0:0:0]:7687`. Note the runbook's
   step-7 "verify end-to-end" only ever exercised the **proxy** leg (local stack)
   — the private-network leg was first exercised by this incident.
3. **The deployed api had no `neo4j` package at all** — the P3 deps (`neo4j`,
   `pyyaml`) were added to `pyproject.toml` but never mirrored into
   `requirements.txt`, which is what the Railway builder installs (gotchas doc,
   rule 2). `pyyaml` arrived transitively via langchain so the api *booted*;
   every graph touch then died on `ModuleNotFoundError`, swallowed by the
   degrade path. Diagnosed by `railway ssh` into the api container (`python3 -c
   "import neo4j"`); fixed in `5dca3b0`, which also added a sanitized
   `kgquery: graph probe failed (<ExceptionClass>)` log line so the next silent
   degrade names itself.

Layers 1–2 were config fixed in the Railway console; layer 3 was the one in the
repo. After all three: status shows the live counts, and the live agent answers
competency questions (verified end-to-end 2026-07-08).

## What's deferred

- **P4 (router) and P5 (hybrid)** stay directional in the plan until P3 is live and the golden numbers exist. (U13 completed 2026-07-06 — P3 is live; first golden numbers recorded above.)
