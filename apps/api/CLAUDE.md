# apps/api

FastAPI service. Railway-internal only — no public domain. Reachable from the `web` service over Railway's project-internal network.

For project-wide context (stack, conventions, plans, writeups), see the root [CLAUDE.md](../../CLAUDE.md).

## Local quick-start

Activate the shared uv env (one-time setup in `apps/api/README.md`), then:

```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv/Scripts/activate
uvicorn app.main:app --reload --port 8000

pytest
ruff check . && ruff format --check .
```

## Notes

- `/health` returns `200 { "status": "ok", "db": "ok" | "down" }` — see [docs/conventions/stack.md](../../docs/conventions/stack.md#api-contract-p0).
- DB pool is lazy-initialized on first request — startup never blocks on DB availability.
- Errors connecting to Postgres are logged with a sanitized message; never log the raw exception or `DATABASE_URL`.
