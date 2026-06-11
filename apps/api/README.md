# apps/api

FastAPI service for avird-2026. **Railway-internal only** — no public domain. See [docs/conventions/stack.md](../../docs/conventions/stack.md) for the full env-var contract and exposure model.

P0 ships only `GET /health`.

## Local dev

The project's shared dev env is managed with `uv` and lives outside the repo at `~/claude_code_repos/my-uv-envs/avird-2026-app/.venv`. One-time setup:

```bash
uv venv ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv --python 3.14
uv pip install --python ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv \
  -r ~/claude_code_repos/my-uv-envs/avird-2026-app/requirements.txt
```

Then activate before working:

```bash
..\my-uv-envs\avird-2026-app\.venv\Scripts\Activate.ps1 # Powershell
# source ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv/Scripts/activate    # Windows
# or: source ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv/bin/activate

cp .env.example .env                                  # then edit DATABASE_URL
uvicorn app.main:app --reload --port 8000 --env-file .env
```

The project's `pyproject.toml` is the source of truth for what Railway installs in production. The shared env's `requirements.txt` mirrors those deps (plus the `tools/` harness deps) for local dev.

```bash
curl localhost:8000/health
# {"status":"ok","db":"ok"}    # DATABASE_URL points at a reachable Postgres
# {"status":"ok","db":"down"}  # DB unreachable (still 200; never raises)
```

## Tests

```bash
pytest                  # run from apps/api/ with the shared venv activated
```

Tests use FastAPI's `dependency_overrides` and don't require a running Postgres. The unreachable-host test exercises the real `check_db()` against `127.0.0.1:1` to prove it returns `"down"` cleanly.

## Lint + format

```bash
ruff check .
ruff format --check .    # check only
ruff format .            # apply
```

The project's `/ship` slash command runs both as part of its gate.

## Deploy (Railway)

These are the manual steps. Run them once when setting up the project; they don't repeat per push.

1. **Create the service.** In the avird-2026 Railway project, add a service from this repo with **root directory = `apps/api`**.
2. **Keep it internal.** Do *not* attach a public Railway domain. The `web` service reaches `/health` over the project-internal network via the `API_URL` reference variable.
3. **Wire `DATABASE_URL`.** In this service's variables, add a reference variable to the Postgres service's `DATABASE_URL`. Never paste a literal connection string.
4. **Start command.** Auto-detected from `Procfile`: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
5. **Verify.** From a Railway shell on this service, run `curl localhost:$PORT/health` — expect `{"status":"ok","db":"ok"}`. End-to-end liveness from outside is asserted by the `web` service's index page rendering "API: ok".

## Conventions

- DB pool is lazy-initialized on first request — startup doesn't block on DB availability.
- `check_db()` swallows every exception and reports `"down"`. The route returns 200 either way so Railway healthchecks pass on transient blips.
- Errors connecting to Postgres log a sanitized message (`"DB connection failed"`) — never the raw exception or `DATABASE_URL`.
