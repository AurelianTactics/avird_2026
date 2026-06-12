# Stack

The single source of truth for which services run where, what env vars they read, and how cross-service references work. Subsequent phases update this file as they add nodes; do not invent new conventions elsewhere.

## Services (Railway project: `avird-2026`)

| Service | Source | Public? | Reads | Exposes |
|---------|--------|---------|-------|---------|
| `web`   | `apps/web/` (Next.js, App Router, TypeScript) | **Yes** — only public origin | `API_URL` | the public site |
| `api`   | `apps/api/` (FastAPI + asyncpg) | **No** — Railway-internal only | `DATABASE_URL`, `PORT` | `/health` (and future P1+ data routes) |
| `db`    | Railway Postgres 16 template | No | — | `DATABASE_URL` (injected) |

### Public vs. internal exposure

The `api` service has **no public Railway domain**. External traffic flows `visitor → web → api` over Railway's project-internal network. This is deliberate: P1+ data endpoints inherit a tight surface and don't have to retrofit auth or rate-limiting in P0.

If Railway's internal hostname doesn't resolve for some reason, the temporary fallback is to attach a public domain to `api` and switch `API_URL` to it — leave a TODO and revisit; not a blocker for P0.

## Env-var contract

| Variable | Set by | Consumed by | Notes |
|----------|--------|-------------|-------|
| `DATABASE_URL` | Railway (Postgres reference variable) | `api` | Never committed. `.env.example` placeholder only. Sanitized in logs on failure. |
| `API_URL`      | Railway (reference variable to `api` service's internal hostname) | `web` (server-side only) | **No `NEXT_PUBLIC_` prefix** — server components only. Never bundled into browser. |
| `PORT`         | Railway (per-service) | `web`, `api` | FastAPI starts via `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. |
| `ANTHROPIC_API_KEY` | local `.env` (gitignored) | `ontology/` scripts | Paid LLM calls (discovery, extraction, golden pre-label). Never committed; tests stub the client and need no key. |
| `NEO4J_URI` | local `.env` (gitignored) | `ontology/graph_load.py` | AuraDB Free `neo4j+s://...` connection URI from the Aura console. |
| `NEO4J_USERNAME` | local `.env` (gitignored) | `ontology/graph_load.py` | AuraDB credential (usually `neo4j`). |
| `NEO4J_PASSWORD` | local `.env` (gitignored) | `ontology/graph_load.py` | AuraDB credential, shown once at instance creation. |
| `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` | local `.env` (optional) | `ontology/` LangGraph runs | Optional run tracing; JSONL run records remain the durable system of record. |

For local dev, both apps fall back to `.env.example` defaults (`http://localhost:8000` for `API_URL`, a local Postgres URL for `DATABASE_URL`).

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

## Ports

| Service | Local dev | Railway |
|---------|-----------|---------|
| `web`   | `3000` (Next default) | `$PORT` |
| `api`   | `8000`               | `$PORT` |
| `db`    | `5432`               | `$PORT` (Railway-managed) |
