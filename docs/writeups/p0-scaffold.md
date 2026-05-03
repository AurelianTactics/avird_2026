---
phase: P0
date: 2026-05-01
plan: ../plans/2026-04-28-001-feat-phase-0-scaffold-plan.md
---

# P0 — Scaffold

The empty deployed substrate: Next.js + FastAPI + Postgres on Railway, plus the compound-engineering conventions (CLAUDE.md, slash commands, hooks) and an agent-runnable site-verification harness. P0 ships nothing about the data — it ships the rails everything else compounds on.

## What shipped

- **`apps/web/`** — Next.js 15 (App Router, TypeScript). Two pages: `/` placeholder index, `/about`. The index server-side-fetches `${API_URL}/health` and renders one of `API: ok` / `API: down` / `API: unreachable`. Vitest + Testing Library suite covers all four states (ok, down, unreachable on throw, unreachable on non-2xx) plus the About heading.
- **`apps/api/`** — FastAPI service with one route: `GET /health` → `{"status": "ok", "db": "ok" | "down"}`. Asyncpg pool, lazy-init on first request, sanitized error logging. Pytest suite uses dependency overrides for the route shape and exercises the real `check_db()` against an unreachable host to prove it never raises.
- **Postgres 16** provisioned on Railway as `db`. Empty — schema lands in P1.
- **`tools/verify_site.py`** — agent-runnable harness (R9.5). httpx + BeautifulSoup, three checks: status (`/` and `/about` return 200), internal-link resolution, expected-text assertions on each page. Treats `API: down` and `API: unreachable` as failures. 8 fixture-tested scenarios.
- **Compound-engineering substrate.** `.claude/settings.json` with a `PostToolUse` hook that runs `ruff format` on `apps/api/**/*.py` and `prettier --write` on `apps/web/**/*.{ts,tsx}`. Two slash commands: `/ship` (lint+format+test gate) and `/verify-site`.
- **Progressive-disclosure docs.** Root `CLAUDE.md` is a short index; depth lives in `docs/conventions/{stack,workflow}.md`, `docs/writeups/`, and `docs/solutions/`. Per-service stub `CLAUDE.md`s under `apps/web/` and `apps/api/` exist so an agent invoked inside a service still finds the project map.

## Env-var contract

| Variable        | Set by                                  | Consumed by | Notes |
|-----------------|-----------------------------------------|-------------|-------|
| `DATABASE_URL`  | Railway Postgres reference variable     | `api`       | Never committed; never logged. |
| `API_URL`       | Railway reference to `api`'s **internal** hostname | `web` server-side | No `NEXT_PUBLIC_` prefix. Routes that read it set `dynamic = 'force-dynamic'`. |
| `PORT`          | Railway per-service                      | `web`, `api` | uvicorn binds `0.0.0.0:$PORT`. |

Only the `web` service has a public Railway domain. `api` is internal-only by design — P1+ data routes inherit a tight surface and don't have to retrofit auth or rate-limiting.

## How to use

- **`/ship`** — run before commit. Gates on `ruff` + `npm run lint` + `pytest` in both Python projects + `npm test` in web. Tolerates empty suites.
- **`/verify-site <url>`** — run after deploy. Punch list of `[ok]` / `[fail]` lines for each check.
- Format hook fires automatically on Edit/Write inside `apps/api/**/*.py` and `apps/web/**/*.{ts,tsx}`.

## Why these choices

- **`fastapi[standard]` + `asyncpg`, no ORM yet.** P0 has one trivial query; ORM tooling is a P1 decision once there's a schema worth modeling.
- **Internal-only `api`.** Tightens the surface for free. P1+ data routes are reached via Next.js server components or route handlers, never directly from the browser.
- **Vitest over Jest.** Lighter, fewer App-Router pitfalls, plays well with the existing TS toolchain.
- **httpx + BeautifulSoup harness, no Playwright.** P0 pages are server-rendered and the assertion set is small. Playwright is the documented upgrade path for P5 R27 if visual or JS-rendered assertions arrive.
- **Single shared uv env at `~/claude_code_repos/my-uv-envs/avird-2026-app/`.** One env covers `apps/api` runtime + `tools/` harness + dev/test deps; both human and agent run the same commands and get the same results.

## What surprised me

- Writing the harness's link-resolution check made the lack of internal links on the placeholder index obvious. Added `<a href="/about">` and `<a href="/">` so the check has something to traverse, otherwise it's a vacuous pass.
- The Next.js build-vs-runtime gotcha (`force-dynamic` + `cache: 'no-store'`) is now load-bearing: without it, the index would prerender at build time when `API_URL` isn't reachable, baking `API: unreachable` into the bundle. Documented in `docs/conventions/stack.md`.

## What's deferred

- ORM / migration tooling (likely SQLAlchemy + Alembic) — P1.
- Final assertion strings for `/verify-site` are intentionally easy to evolve; the config block at the top of `tools/verify_site.py` is the single edit point.
- AGENTS.md is not adopted — Claude Code is the only AI tool of record. Re-evaluate if a second tool gets adopted in P2.
- No CI beyond Railway-managed deploy on push. Heavier CI is deferred to P5 when evals need it.

## Manual deploy steps

The code is in. Railway provisioning is the user's box to check off:

1. **Project + Postgres** — see `docs/conventions/stack.md` (services `web`, `api`, `db`).
2. **`apps/api`** — service from this repo, root dir `apps/api`, **no public domain**, `DATABASE_URL` referenced from the Postgres service. Procfile-driven start command. (Steps in `apps/api/README.md`.)
3. **`apps/web`** — service from this repo, root dir `apps/web`, public domain attached, `API_URL` referenced from the api service's **internal** hostname. (Steps in `apps/web/README.md`.)
4. **Verify** — `python tools/verify_site.py --base-url <web-url>` or `/verify-site <web-url>`. All checks should be `[ok]` once both services are deployed.
