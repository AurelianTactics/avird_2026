# avird-2026

A learning-by-building portfolio over NHTSA's Standing General Order on Crash Reporting (autonomous-vehicle crash data). The site ingests, explores, models, and lets you "talk to" the dataset — and the build workflow itself (slash commands, hooks, evals, agents) is part of what's being learned. Stack: Next.js + FastAPI + Postgres on Railway.

## Run locally

Python deps live in a shared `uv` env outside the repo at `~/claude_code_repos/my-uv-envs/avird-2026-app/`. One-time setup:

```bash
uv venv ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv --python 3.14
uv pip install --python ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv \
  -r ~/claude_code_repos/my-uv-envs/avird-2026-app/requirements.txt
```

Then:

```bash
# api
source ~/claude_code_repos/my-uv-envs/avird-2026-app/.venv/Scripts/activate
cd apps/api
uvicorn app.main:app --reload --port 8000

# web (separate terminal)
cd apps/web
npm install
npm run dev    # http://localhost:3000
```

`apps/web` reads `API_URL` (default `http://localhost:8000`). `apps/api` reads `DATABASE_URL` (any reachable Postgres). See `apps/web/.env.example` and `apps/api/.env.example`.

## Project guide

Start at [CLAUDE.md](CLAUDE.md) for the full map.
