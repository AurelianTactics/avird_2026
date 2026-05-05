---
title: "Railway monorepo deploy gotchas: railpack, IPv6 private network, Procfile YAML, cross-service variables"
date: 2026-05-05
category: docs/solutions/tooling-decisions
module: deploy
problem_type: tooling_decision
component: tooling
severity: high
applies_when:
  - "deploying a monorepo to Railway with per-service Root Directory"
  - "using railpack's Python builder with pyproject.toml"
  - "two Railway services need to talk over private networking"
  - "writing a Procfile for a railpack-built service"
  - "referencing another service's PORT via ${{svc.PORT}}"
related_components:
  - apps/api
  - apps/web
  - development_workflow
tags:
  - railway
  - railpack
  - deploy
  - ipv6-private-network
  - procfile-yaml
  - monorepo
---

# Railway monorepo deploy gotchas

## Context

Deploying Phase 0 of avird-2026 — a Next.js web service, a FastAPI api service, and a Postgres database, all as three services inside one Railway project — hit six distinct Railway-specific failures before traffic flowed end-to-end. The api is Railway-internal-only and the web service reaches it over Railway's private network. None of these failures were Python or FastAPI bugs; all six were artifacts of how Railway's railpack builder, runtime shell, private-network DNS, and cross-service variable references behave. Capture them in one place so the next Python-on-Railway deploy doesn't re-walk the same minefield.

## Guidance

### 1. Invoke Python entry points via `python -m`, never bare

Railway's runtime shell does not reliably expose pip-installed console scripts on `PATH`. `uvicorn app.main:app` fails with `command not found`; `python -m uvicorn app.main:app` always works because it goes through the Python module system.

```
# Procfile
web: "python -m uvicorn app.main:app --host :: --port $PORT"
```

Apply the same `python -m` rule to gunicorn, alembic, pytest, and anything else you'd normally call by its console-script name.

### 2. Pin the Python version *inside* the Root Directory, and ship a `requirements.txt`

When a service's Railway **Root Directory** points at a subpath (e.g. `apps/api/`), railpack only sees that subtree. A `.python-version` at the repo root is silently ignored, and `pyproject.toml`-based dep resolution has been flaky for nested roots. Two fixes, both inside the Root Directory:

```
apps/api/.python-version       # contents: 3.14
apps/api/requirements.txt      # mirrors pyproject runtime deps
```

```
# apps/api/requirements.txt
fastapi[standard]>=0.115
asyncpg>=0.29
```

Keep `pyproject.toml` as the source of truth for local dev; treat `requirements.txt` as the deploy-artifact mirror.

### 3. Keep the Variables tab clean — no empty keys

Railpack mounts every Variables-tab entry as a buildkit secret. An empty/blank key crashes the build with:

```
failed to solve: secret ID missing for "" environment variable
```

Fix is purely UI: open the service's Variables tab and delete the blank row. Worth grepping for if a build dies before producing any Python output.

### 4. Bind to `::` (IPv6), not `0.0.0.0`, for private networking

Railway's private network (`*.railway.internal`) is **IPv6-only**. A service bound to `0.0.0.0` is reachable on the public IPv4 stack but invisible to private-network callers — DNS resolves the consumer to a v6 address that never accepts a connection. Symptom: the api looks healthy in its own logs, but every web-side fetch fails.

```
# wrong — IPv4 only, invisible on private network
--host 0.0.0.0

# right — IPv6 wildcard, dual-stack accepts IPv4 too
--host ::
```

uvicorn should log `Uvicorn running on http://[::]:8080` once this is correct.

### 5. Quote any Procfile command containing `:` characters

Railpack parses the Procfile as YAML. `--host ::` contains consecutive colons which YAML reads as nested mapping syntax and rejects with `mapping values are not allowed in this context`. Wrap the entire command in double quotes so YAML treats it as a literal scalar; `$PORT` still expands at shell time.

```
# Procfile — final form
web: "python -m uvicorn app.main:app --host :: --port $PORT"
```

### 6. Hardcode the port in cross-service URLs — `${{...PORT}}` does not resolve

Railway's cross-service variable references (`${{api.RAILWAY_PRIVATE_DOMAIN}}`, etc.) work for most variables, but **`PORT` resolves to empty**. A naive `API_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:${{api.PORT}}` produces `http://api.railway.internal:` with no port. Hardcode the port literally on the consumer side; railpack's default Python service port is `8080`.

```
# web service Variables tab
API_URL=http://api.railway.internal:8080
```

## Why This Matters

Each of these failures looks like a Python/FastAPI bug from inside the application logs but is actually a Railway platform contract. Diagnosing them blind costs hours per issue — most have non-obvious symptoms (silent IPv6 mismatch, blank-port URL, ignored `.python-version`) that don't point at the real cause. Documenting the cluster turns a multi-hour debugging slog into a checklist.

## When to Apply

- **Any Python service deployed on Railway** — apply rules 1, 2, 5.
- **Any Railway service with a nested Root Directory** (monorepo subpath deploy) — apply rule 2 specifically; pin Python and ship `requirements.txt` *inside* the root.
- **Any Railway project using private networking between services** — apply rules 4 and 6; bind to `::` and hardcode the port in consumer `*_URL` vars.
- **Any railpack build that dies before producing language-level output** — check rule 3 (empty Variables-tab entries) before deeper investigation.
- **Any Procfile command containing `:` characters** (IPv6 hosts, time formats, URL schemes in literal args) — apply rule 5 and quote the whole command.

## Examples

**Final `apps/api/Procfile`:**

```
web: "python -m uvicorn app.main:app --host :: --port $PORT"
```

**Final `apps/api/requirements.txt`:**

```
fastapi[standard]>=0.115
asyncpg>=0.29
```

**Final `apps/api/.python-version`:**

```
3.14
```

**Web service `API_URL` variable:**

```
API_URL=http://api.railway.internal:8080
```

**Before/after host binding:**

```
# before — web sees "API: unreachable"
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT

# after — reachable over Railway private network
"python -m uvicorn app.main:app --host :: --port $PORT"
```

**Successful runtime log line confirming the fix landed:**

```
Uvicorn running on http://[::]:8080
```

## Related

- Plan: [docs/plans/2026-04-28-001-feat-phase-0-scaffold-plan.md](../../plans/2026-04-28-001-feat-phase-0-scaffold-plan.md)
- Stack contract: [docs/conventions/stack.md](../../conventions/stack.md)
- Phase 0 writeup: [docs/writeups/p0-scaffold.md](../../writeups/p0-scaffold.md)
