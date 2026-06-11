# Local verification pipeline — seeded stack, evidence loop, Stop gate

Plan: [2026-06-09-001-feat-local-verification-pipeline-plan.md](../plans/2026-06-09-001-feat-local-verification-pipeline-plan.md)
Origin: [the W1–W2 incident](../solutions/workflow-issues/agent-shipped-website-without-running-verification-loop.md) — ten units, 71 green tests, zero pages ever rendered.

## What shipped

Four layers, each backed by the one below:

1. **Substrate** — `tools/local_db_setup.py` creates `avird_dev` on the native
   PG 17 (`:5432`); the existing `db/run_pipeline.py` seeds it with the real
   NHTSA data (3,120 treated rows / 2,344 canonical, 12s, idempotent, zero new
   seed code). `tools/dev_stack.py up|status|down` orchestrates api + web with
   the prod env contract; `up` from cold is ~15s and is a no-op when healthy.
2. **One action** — `/verify-local`: ensure stack → drive each changed route
   through the `/verify-page` perception loop → record evidence → run
   `verify_site.py` against `localhost:3000`.
3. **Evidence** — `tools/verify_evidence.py`: per-route JSON in gitignored
   `.verify/` (result, console count, screenshot path, content hashes of every
   affecting file). Freshness is hash-based, not timestamp-based.
4. **Enforcement** — `mark_web_pending.py` (PostToolUse) marks page-affecting
   edits as debt; `verify_gate.py` (Stop) blocks end-of-turn until every
   pending route has fresh passing evidence, naming the exact
   `/verify-local <route>` commands. Debt persists across sessions.

140 tests across tools (80), api (38), web (22); lint/format clean.

## Drill results (all five steps, executed live)

| Step | Result |
|------|--------|
| Cold start | seed 12.1s + `up` 15.4s ≈ 28s from nothing to a healthy, data-backed stack |
| Edit page, try to stop | hook marked the file pending **live**; gate blocked with `/verify-local /about` |
| Run the loop | evidence recorded (fail first, honestly — see findings), gate passed after fixes |
| Deliberate bug | unnecessary — the loop found five real ones instead (below) |
| Docs-only session | pending stayed empty; gate allowed silently |

The freshness rule also fired for real mid-drill: `/about`'s evidence went
stale when the shared `api.ts` was fixed afterward, and `check` named exactly
that file and that route.

## What the loop caught that 140 green tests could not

1. **favicon.ico 404** — console error on every page since W1.
2. **React duplicate-key error** — the raw list keys rows by `report_id`,
   which repeats for resubmissions; visible on page 1 of real data, invisible
   to unit tests with unique fixtures.
3. **localhost vs 127.0.0.1** — the web app's server-side fetch failed
   silently on Windows (Node resolves `localhost` → `::1`; uvicorn binds IPv4
   only). Local dev was rendering the degraded "could not load" state and no
   test knew. Prod never hits it (`API_URL` is a Railway hostname).
4. **Interpreter drift** — the agent's plain `python` is the system 3.12, not
   the shared venv; `dev_stack` now self-locates the venv for the api spawn
   (`AVIRD_APP_PYTHON` > documented venv path > `sys.executable`).
5. **Git-Bash argument mangling** — MSYS rewrote `--route /about` into
   `C:/Program Files/Git/about` (plus a cp1252 crash printing `→`). `record`
   now rejects mangled routes and takes slash-less ones (`.` = root).

## R3 prompt audit (each prompt = a defect)

The build/setup half of the session prompted constantly; the verification
loop itself did not once invoked correctly. Causes, in order of pain:

- **Wrong invocation shape (agent error):** compound PowerShell commands can
  never match the committed `Bash(python tools/...)` allowlist. The loop is
  prompt-free only in its exact documented shape.
- **One-time setup (by design):** installs, psql probes, doc fetches, git
  commits are deliberately not allowlisted.
- **Remaining genuine defect:** `python tools/verify_site.py` needs the
  shared venv on PATH for the agent's shell (`bs4`). One-time fix: add
  `~/claude_code_repos/my-uv-envs/avird-2026-app/.venv/Scripts` to PATH for
  agent sessions, per the existing `/ship` assumption in workflow.md.

## Deferred / known limits

- Human (non-agent) edits don't mark pending — the gate gates agent turns by
  design; `/verify-site` and prod remain the net for everything else.
- Evidence honesty is procedural (record-fail-first), not enforced; the gate
  guarantees the loop *ran* and artifacts let the user audit how well.
- Railway dev environment, api-only gate scope, screenshot-diff tooling: all
  deferred per the plan's scope boundaries.
