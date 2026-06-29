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
- The live debate routes (`app/debate.py`) make paid LLM calls and need `ANTHROPIC_API_KEY` at runtime (new — the service was previously key-free). They are guarded by hard caps + a `$5`/day budget guard (`DEBATE_DAILY_BUDGET_USD`). The read-only fault route (`app/fault.py`) has **no** LLM deps. Tests stub the LLM client via overridable dependencies and need no key — see [stack.md](../../docs/conventions/stack.md#fault-judge--debate-routes-p1).
- The NL-query agent (`app/derived/agent.py`, `POST /derived/query`) is the other paid LLM surface — one Claude call per request, bounded to a 500-char input and `max_tokens=256`. It has its **own** daily budget guard (`app/derived/budget.py`, `DERIVED_DAILY_BUDGET_USD`, default `$2`, ledger table `derived_spend`) separate from debate's so the two can't drain each other. Over the cap the agent degrades to the default (unfiltered) view rather than erroring. The default `/derived/heatmaps` render is deterministic and LLM-free. The guard is injected via `get_budget_guard`; tests override it with the in-memory variant (no DB, no key).
