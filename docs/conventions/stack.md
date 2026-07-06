# Stack

The single source of truth for which services run where, what env vars they read, and how cross-service references work. Subsequent phases update this file as they add nodes; do not invent new conventions elsewhere.

## Services (Railway project: `avird-2026`)

| Service | Source | Public? | Reads | Exposes |
|---------|--------|---------|-------|---------|
| `web`   | `apps/web/` (Next.js, App Router, TypeScript) | **Yes** — only public origin | `API_URL` | the public site |
| `api`   | `apps/api/` (FastAPI + asyncpg) | **No** — Railway-internal only | `DATABASE_URL`, `PORT` | `/health` (and future P1+ data routes) |
| `db`    | Railway Postgres 16 template | No | — | `DATABASE_URL` (injected) |
| `neo4j` | Railway template ([neo4j-graph-database](https://railway.com/deploy/neo4j-graph-database)): `neo4j:5.x-community` + `/data` volume | TCP proxy only (dev, toggleable) | — | bolt on 7687: private network for `api`, public TCP proxy for local dev |

### Public vs. internal exposure

The `api` service has **no public Railway domain**. External traffic flows `visitor → web → api` over Railway's project-internal network. This is deliberate: P1+ data endpoints inherit a tight surface and don't have to retrofit auth or rate-limiting in P0.

If Railway's internal hostname doesn't resolve for some reason, the temporary fallback is to attach a public domain to `api` and switch `API_URL` to it — leave a TODO and revisit; not a blocker for P0.

## Env-var contract

| Variable | Set by | Consumed by | Notes |
|----------|--------|-------------|-------|
| `DATABASE_URL` | Railway (Postgres reference variable) | `api` | Never committed. `.env.example` placeholder only. Sanitized in logs on failure. |
| `READONLY_DATABASE_URL` | local `.env` (gitignored); Railway `api` service (when P1 text-to-SQL is exposed) | the open-ended text-to-SQL agent (`app/nlsql/`) | Connection string for a Postgres role with `SELECT`-only on `treated_incident_reports` (plan P1, KTD-1). Provisioned by `tools/setup_readonly_role.py` from this URL; see "Text-to-SQL read-only role" below. Local-first: absent ⇒ the nlsql CLI prints a one-line setup hint. Never committed. |
| `API_URL`      | Railway (reference variable to `api` service's internal hostname) | `web` (server-side only) | **No `NEXT_PUBLIC_` prefix** — server components only. Never bundled into browser. |
| `PORT`         | Railway (per-service) | `web`, `api` | FastAPI starts via `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. |
| `ANTHROPIC_API_KEY` | local `.env` (gitignored); Railway `api` service (runtime) | `ontology/` + `fault/` scripts, **and the `api` runtime** | Paid LLM calls, read at call time, never logged (sanitized degrade, mirroring `DATABASE_URL`). Offline: discovery/extraction/golden pre-label (ontology) and the fault judge batch (`fault/`). Runtime: the live debate routes (`POST /incidents/{id}/debate/{turn,judge}`) and the NL-query agent (`POST /derived/query`) — `api` was previously key-free. **Do not** add it to `web`. Absent ⇒ the site still renders; only those LLM routes degrade to their fallbacks (debate paused; query → default view). Never committed; tests stub the client and need no key. |
| `NEO4J_URI` | local `.env` (gitignored); Railway `api` service (P3 KG queries) | `ontology/graph_load.py`, `app/kgquery/agent.py` | Railway Neo4j CE bolt URI. Two forms: the **private-network** address (`bolt://neo4j.railway.internal:7687`) on the `api` service, and the **public TCP proxy** address (`bolt://<proxy-host>:<proxy-port>`) in the local `.env`. The proxy doesn't terminate TLS — unencrypted bolt + strong password, accepted for a rebuildable graph of public data; toggle the proxy off between dev sessions. |
| `NEO4J_USERNAME` | local `.env` (gitignored); Railway `api` service | `ontology/graph_load.py`, `app/kgquery/agent.py` | Neo4j credential (usually `neo4j`). |
| `NEO4J_PASSWORD` | local `.env` (gitignored); Railway `api` service | `ontology/graph_load.py`, `app/kgquery/agent.py` | Neo4j credential, set via `NEO4J_AUTH` at instance creation. Strong password — the dev TCP proxy is unencrypted. |
| `KGQUERY_DAILY_BUDGET_USD` | Railway `api` service / local `.env` | `app/kgquery/budget.py` | Daily USD cap for `POST /kgquery/ask` (default `$2`, ledger `kgquery_spend`, separate from the debate/derived/nlsql/rag guards). Per-call estimate is measured from the rendered graph card (KTD-5). |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | local `.env` (optional) | `ontology/` LangGraph runs | Optional run tracing; JSONL run records remain the durable system of record. |
| `HF_TOKEN` | local `.env` (gitignored); Railway `api` service (when P2 RAG is exposed) | `eda/build_narrative_embeddings.py` (offline) and the RAG query embedder (`app/rag/agent.py`, runtime) | HuggingFace Inference token for `bge-base` embeddings. Absent ⇒ `POST /rag/ask` degrades to a service notice; the rest of the site is unaffected. Never committed. |
| `RAG_STORE` / `RAG_DATASET_ID` | local `apps/api/.env` | `app/rag/routes.py` store selection | `RAG_STORE=memory` selects the in-memory corpus — the **local default**, because `CREATE EXTENSION vector` fails on local Windows PG 17 (resolved plan open question). Unset/other ⇒ pgvector over `DATABASE_URL` (production path; confirm the extension on Railway PG 16 before live exposure). |
| `RAG_DAILY_BUDGET_USD` / `RAG_JUDGE_ENABLED` | Railway `api` service / local `.env` | `app/rag/budget.py`, `app/rag/routes.py` | Daily USD cap for `POST /rag/ask` (default `$2`, ledger `rag_spend`, separate from the debate/derived/nlsql guards). `RAG_JUDGE_ENABLED=0` disables the sonnet faithfulness judge (structural citation gate still runs). |

For local dev, both apps fall back to `.env.example` defaults (`http://localhost:8000` for `API_URL`, a local Postgres URL for `DATABASE_URL`). `ANTHROPIC_API_KEY` has no default — leave it unset locally and the NL-query path returns the unfiltered default view.

## Agent path (W5)

The `api` service gains one LLM-backed route — `POST /derived/query` — built as a small **LangGraph** graph with **Claude** (Anthropic SDK) mapping natural language to a structured, allow-list-validated filter (never model-authored SQL). It is one of the sanctioned dependency-weight exceptions to R22 (LangGraph + Anthropic, shared with the live debate routes), contained to that route: the default `/heatmaps` render and `GET /derived/heatmaps` stay deterministic and LLM-free, so the site is fully usable with no key configured. Deploy must set `ANTHROPIC_API_KEY` in Railway before the query route works in prod.

Because it's a paid LLM call on a public surface, the route is gated by a **daily USD budget guard** (`app/derived/budget.py`, `DERIVED_DAILY_BUDGET_USD`, default `$2`) — a durable rolling-24h ledger (`derived_spend`) separate from the debate guard's so the two LLM features can't drain each other. Per call it's bounded to a 500-char input and `max_tokens=256`; over the daily cap the agent degrades to the unfiltered default view rather than erroring. The model proposes only candidate filter values that `filters.resolve` validates against the data-layer allow-list, so a prompt-injected query can't reach SQL — the residual exposure is cost/abuse, which the budget guard caps.

## Text-to-SQL read-only role (P1)

The open-ended text-to-SQL agent (plan `docs/plans/2026-06-30-001-feat-agentic-data-access-progression-plan.md`, P1) lets a model author real `SELECT` SQL — defensible only because that SQL executes as a Postgres role that *structurally* can do nothing else (KTD-1). The role has `SELECT` on `treated_incident_reports` and nothing more: no write privileges, no access to any other table (including the `*_spend` ledgers), plus a role-level `statement_timeout` and `work_mem`.

- **Provision (local, idempotent):** `python tools/setup_readonly_role.py`. It reads `READONLY_DATABASE_URL` to derive the role name, password, and database, then applies `db/roles/readonly_role.sql` over the admin `DATABASE_URL`. A second run reports the role exists and re-asserts the grants.
- **Provision (Railway/prod):** run `db/roles/readonly_role.sql` once with `psql -v role=… -v password=… -v dbname=…`, then set `READONLY_DATABASE_URL` on the `api` service. The agent connects as this role, never as the owning `DATABASE_URL` role.
- **Web delivery (live-exposure gate passed):** the agent is mounted as `POST /nlsql/query` + `GET /nlsql/schema` on the api, reached through a same-origin `web` proxy (`/api/nlsql/query`) by the `/nlsql` page ("Ask the data"). The route inherits the budget-guard discipline: its own daily cap (`NLSQL_DAILY_BUDGET_USD`, default `$2`, ledger `nlsql_spend`) with a per-call estimate sized to the larger P1 prompt (KTD-5). It never 500s — agent failures surface as `fallback=true`.
- **Local-first iteration:** the agent also runs via `python -m app.nlsql.cli` against the seeded local DB (no route needed); absent `READONLY_DATABASE_URL` it prints a one-line setup hint pointing at the script above.

## Narrative RAG store + toolchain (P2)

Phase 2 of the agentic progression (`app/rag/`) retrieves crash narratives by cosine similarity over the existing `bge-base` embeddings.

- **Store:** `db/pgvector_setup.sql` enables `vector` and creates `narrative_embeddings(incident_id, embedding vector(768), narrative)`. `app/rag/store.py` retrieves via `embedding <=> $1` (pgvector) with a vendored numpy-cosine **in-memory fallback** behind the same `retrieve` signature (KTD-3).
- **Ingest is a re-derive, not a parquet load:** the embedding cache stores only `{text_hash, vector}` — no incident id, no narrative. `app/rag/ingest.py` re-derives the deduped `(Same Incident ID, narrative)` rows from the raw `data/nhtsa/` CSVs (via the `eda` dedup pipeline), re-hashes each narrative, and joins to the cache vector by hash; unmatched rows are reported, never dropped.
- **Web delivery (live-exposure gate passed):** the agent is mounted as `POST /rag/ask` + `GET /rag/status` on the api, reached through a same-origin `web` proxy (`/api/rag/ask`) by the `/rag` page ("Ask the narratives"). Its own daily cap (`RAG_DAILY_BUDGET_USD`, default `$2`, ledger `rag_spend`) sizes the per-call estimate to the pricier judge call. It never 500s — failures degrade to a retrieval-only fallback.
- **Dependency strategy (updated for the live route):** because `rag/routes.py` mounts the store in the FastAPI app, the minimal runtime deps are declared in `apps/api`'s `pyproject.toml` + `requirements.txt`: `numpy` (the store's vendored cosine path) and `huggingface_hub` (lazy query embedding), plus `sqlglot` for P1's validator. The heavy ingest deps (`pandas`, `pyarrow`, the flat `eda` modules) remain **offline-only** — lazy-imported by the CLI/ingest/eval from the shared dev venv, never loaded by the api at runtime.
- **pgvector availability (open question):** stock Windows PG 17 may lack `vector`; if `CREATE EXTENSION vector` fails locally, the in-memory path is the local default and pgvector parity is validated against Railway PG 16.

## Knowledge-graph queries (P3)

Phase 3 of the agentic progression (`app/kgquery/`) maps natural language to read-only Cypher over the ontology graph (plan `docs/plans/2026-06-30-001-feat-agentic-data-access-progression-plan.md`, P3).

- **Graph backend: Neo4j Community Edition on Railway**, one instance for dev and prod. Replaces AuraDB Free: no 72h idle pause, no idle deletion; costs a small always-on container (~$2–5/mo). Prod (`api`) reaches it over the **private network** (`bolt://neo4j.railway.internal:7687`); local dev over the **public TCP proxy** on the bolt port (unencrypted `bolt://` — strong password, toggle the proxy off between sessions).
- **Provision (one-time, Railway console):** deploy the official template — <https://railway.com/deploy/neo4j-graph-database> — **into the existing `avird-2026` project** (it must share the `api` service's private network). The template runs `neo4j:5.x-community` with a `/data` volume and the bolt TCP proxy pre-wired. At the prompts: set `NEO4J_AUTH=neo4j/<strong-password>`; leave `NEO4J_PLUGINS` empty (the kgquery validator rejects `CALL` wholesale, so APOC is unused attack surface). Then add the memory settings the template leaves optional: `NEO4J_server_memory_heap_max__size=512m`, `NEO4J_server_memory_pagecache_size=128m` — plenty, the graph is the extracted subgraph (~143 incidents).
- **The graph is rebuildable, never authoritative.** The extraction JSONL artifacts are the source of truth; rebuild is `python ontology/graph_load.py` (`--reset --yes` first to wipe) with `NEO4J_*` pointing at the instance. The artifacts are gitignored and live in the `avird-2026-ontology-v001` checkout — copy `ontology/artifacts/extractions/*.jsonl` **and** the matching `ontology/artifacts/runs/*.summary.json` in before rebuilding (the loader refuses an artifact without its run summary).
- **Safety floor: the read-access-mode transaction, not a credential.** CE has no role management, so every `app/kgquery` graph touch runs `execute_query(routing_=READ)` — the server rejects writes at runtime. On top: a static validator (single statement, write-clause + `CALL` rejection, schema label/relationship allow-list from the frozen `ontology/schema/v001.yaml`, `LIMIT` injection) and an `EXPLAIN` dry-run.
- **Web delivery (planned up front, the P1/P2 lesson):** `POST /kgquery/ask` + `GET /kgquery/status` on the api, reached through a same-origin `web` proxy (`/api/kgquery/ask`) by the `/kg` page ("Ask the graph"). Its own daily cap (`KGQUERY_DAILY_BUDGET_USD`, default `$2`, ledger `kgquery_spend`). It never 500s — agent failures surface as `fallback=true`, a down graph as `graph_available=false`, and the `/kg` page shows a friendly unavailable state. The page carries a persistent "answers cover the extracted subgraph (n≈143)" banner so KG counts aren't mistaken for full-dataset counts.
- **Local-first iteration:** `python -m app.kgquery.cli "which companies had pedestrian incidents?"` (stub model when no key); golden eval via `python tools/eval_kgquery.py` (dev split; `--heldout` for final numbers only).

## Cross-service references

Use **Railway reference variables** for cross-service URLs — never hardcode a hostname into the repo. From the `web` service settings, `API_URL` is set to a reference pointing at the `api` service's internal hostname. New services follow the same pattern.

## Build-vs-runtime

Railway reference variables are populated at request time, not at image build. Code that reads them must run **dynamically**:

- Next.js: any route that fetches `API_URL` adds `export const dynamic = 'force-dynamic'` and uses `cache: 'no-store'`. Otherwise Next prerenders the route at build time and bakes `"API: unreachable"` into the bundle.
- FastAPI: connection pool is **lazy-initialized on first request** so service startup doesn't block on DB availability.

## Trust model

Single-owner project; the repo is not externally writable. Secrets (`DATABASE_URL`, future API keys) are injected by Railway at runtime and never committed. `.env.example` files contain placeholders only. The `api` service logs a sanitized message (e.g., `"DB connection failed"`) on connection failure — never the raw exception text or the connection string.

## API contract (P0)

- `GET /health` → `200 { "status": "ok", "db": "ok" | "down" }`. Returns 200 even when `db` is `"down"` so transient DB blips don't fail Railway healthchecks. The `web` index renders this status as one of `"API: ok"`, `"API: down"`, or `"API: unreachable"` (the last when the fetch itself fails).

## Fault judge + debate routes (P1)

LLM fault features hang off the incident page (see [docs/plans/2026-06-25-001-feat-fault-judge-and-debate-plan.md](../plans/2026-06-25-001-feat-fault-judge-and-debate-plan.md)).

- `GET /incidents/{id}/fault` → the precomputed "insurance adjuster" verdict for one report (`is_av_at_fault`, `av_fault_percentage` 0..1, `short_explanation`, `model`, `fault_version`, `created_at`); `404` when no verdict exists. **Read-only, no LLM deps on this path** — verdicts are computed offline by `fault/judge_batch.py` and stored in `fault_analysis`.
- `POST /incidents/{id}/debate/turn` → one AI advocate message arguing the *opposite* of the visitor's position. Body: `{ user_position, transcript, user_argument }`. **Live LLM, stateless** (the client holds the transcript).
- `POST /incidents/{id}/debate/judge` → a neutral verdict `{ is_av_at_fault, fault_percentage, reasoning }` over the transcript. Live LLM, stateless.
- The debate routes enforce hard caps (max rounds, per-argument + total transcript size → `4xx`) and a process-local rolling-24h USD budget guard (`DEBATE_DAILY_BUDGET_USD`, default `$5`; → `429` once tripped). `web` exposes thin same-origin proxy handlers at `/api/incidents/[id]/debate/{turn,judge}` that re-enforce the caps and forward to the internal `api` via server-only `API_URL`. The internal debate model is `claude-haiku-4-5`, overridable via `DEBATE_MODEL_ID`.

## Local dev env

Python deps for both `apps/api` and `tools/` live in a single shared `uv`-managed virtualenv outside the repo:

```
~/claude_code_repos/my-uv-envs/avird-2026-app/
├── requirements.txt    # union of apps/api + tools deps; mirrors the two pyproject.toml files
└── .venv/              # actual env (Python 3.14)
```

Each project's `pyproject.toml` is the source of truth for **what Railway installs in production**. The shared `requirements.txt` mirrors those deps plus the harness deps so both the user and any agent run tests in the same env. When a `pyproject.toml` dep changes, update `requirements.txt` and run `uv pip install --python ... -r ...` against the shared venv.

Repo Python version: `3.14` (pinned via `.python-version` at the repo root, picked up by `uv` and by Railway's Python builder).

The ontology track runs in its own sidecar env, `~/claude_code_repos/my-uv-envs/avird-2026-ontology/` (**Python 3.12**, pinned LangGraph / langchain-anthropic / neo4j deps) — see [ontology/CLAUDE.md](../../ontology/CLAUDE.md).

## Local database (seeded, native Postgres — no Docker)

Local verification runs against a real `avird_dev` database on the **native Windows PostgreSQL 17** instance (`localhost:5432`; a PG 18 service also runs on `:5433` — don't target it by accident; `local_db_setup.py` prints the server version it connected to). Prod is PG 16; the API's SQL surface is version-insensitive, and `/verify-site` against prod remains the fidelity net.

One-time setup:

1. Copy `.env.example` → `.env` at the repo root and put the real local postgres password in `DATABASE_URL`. Mirror the same value into `apps/api/.env` (copy from `apps/api/.env.example`). Both files are gitignored.
2. `python tools/local_db_setup.py` — creates the `avird_dev` database if absent (idempotent; re-run reports "exists").
3. `python db/run_pipeline.py --manifest-out .verify/manifest` — seeds it with the committed NHTSA CSVs (~5 MB), building the same `treated_incident_reports` prod gets. Idempotent (sha256 ingest guard); re-run any time to re-seed. The `--manifest-out` keeps local batch IDs/timestamps from rewriting the committed manifests under `docs/avird-sgo-database-data-dictionary/` (those track the prod pipeline run).

The db pipeline's deps (`sqlalchemy`, `psycopg`, `pandas`, `numpy`, `python-dotenv`, `matplotlib`) live in the shared app venv's `requirements.txt` so the seed runs from the same env as everything else.

## Local stack (api + web)

`tools/dev_stack.py` orchestrates both services against the seeded local DB with the prod env contract (`DATABASE_URL` from `apps/api/.env`, `API_URL` defaulting to `http://localhost:8000`):

```
python tools/dev_stack.py up        # spawn api (:8000) + web (:3000), poll until healthy
python tools/dev_stack.py status    # one [ok]/[fail] line per service; api line shows db state
python tools/dev_stack.py down      # taskkill the recorded process trees, clear pidfile
```

`up` is idempotent — already-healthy services are reported, never double-spawned. PIDs land in `.verify/pids.json`, service logs in `.verify/logs/` (both gitignored). The api spawns via `python -m uvicorn` (console scripts are unreliable on PATH — see the Railway-gotchas learning). The `status` line separates "api down" from "api up, db down" so a data-layer blocker is never mistaken for a dead service. Note `next dev` skips prod-build failure classes (prerender errors); Railway's build + `/verify-site` cover those.

## Ports

| Service | Local dev | Railway |
|---------|-----------|---------|
| `web`   | `3000` (Next default) | `$PORT` |
| `api`   | `8000`               | `$PORT` |
| `db`    | `5432`               | `$PORT` (Railway-managed) |
