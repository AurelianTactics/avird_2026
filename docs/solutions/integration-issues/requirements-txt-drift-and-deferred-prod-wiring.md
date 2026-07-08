---
title: "requirements.txt drift + deferred prod wiring: three agentic pages silently degraded in prod"
date: 2026-07-08
category: integration-issues
module: apps/api
problem_type: integration_issue
component: tooling
symptoms:
  - "/kg permanently shows 'The knowledge graph is unreachable right now' while Neo4j is healthy"
  - "/nlsql shows 'the read-only database role may not be reachable'"
  - "/rag shows 'The narrative index is unavailable right now'"
  - "api logs show only 200s for the degraded endpoints — the degrade paths swallow the exceptions"
root_cause: incomplete_setup
resolution_type: dependency_update
severity: high
tags: [railway, requirements-txt, pyproject, degrade-paths, env-vars, neo4j, prod-wiring]
---

# requirements.txt drift + deferred prod wiring: three agentic pages silently degraded in prod

## Problem

The first prod deploy that actually served the three agentic pages (`/kg`, `/nlsql`, `/rag`)
showed all three in their degraded "service unavailable" states. Each page had a different
cause, all instances of one meta-problem: **prod wiring that the writeups explicitly deferred
to "deploy time" never happened, and the never-500 degrade contracts hid every failure.**

## Symptoms

- `/kg`: graph-down banner, permanently, while the Neo4j service was up and reachable.
- `/nlsql`: "read-only database role may not be reachable" notice.
- `/rag`: "narrative index unavailable" notice; asks logged `rag: query embedding failed`.
- Nothing in the api logs for `/kgquery` — its degrade path caught exceptions without logging.

## What Didn't Work

- **Fixing the Neo4j service config alone.** Two config problems were real and needed fixing —
  the deleted TCP proxy left `NEO4J_server_bolt_advertised__address` dangling (crash-loop trap),
  and the image's `0.0.0.0` default couldn't accept Railway's IPv6-only private-network
  connections (`NEO4J_server_default__listen__address=::` required). But `/kg` stayed down after
  both, because a third layer sat underneath.
- **Auth-mismatch hypothesis.** The Neo4j entrypoint's "changed password only takes effect
  before first start" warning suggested a credential drift; comparing `NEO4J_AUTH` against both
  services and the local `.env` ruled it out.
- **Guessing from outside.** Several console round-trips were spent on variable-editing quirks.
  The decisive evidence came only from inside the environment: `railway ssh --service api --
  python3 -c "import neo4j"` → `ModuleNotFoundError`.

## Solution

Three independent fixes, one per page:

1. **`/kg` — the deployed api had no `neo4j` package.** The P3 deps (`neo4j`, `pyyaml`) were
   added to `pyproject.toml` but never mirrored into `requirements.txt`, which is what Railway's
   builder installs for a nested Root Directory service (gotchas doc, rule 2). `pyyaml` arrived
   transitively via langchain so the api *booted*; every graph touch then raised
   `ModuleNotFoundError`, swallowed by the degrade path. Fix: add both to `requirements.txt`
   (commit `5dca3b0`), plus a sanitized log line on the degrade path
   (`kgquery: graph probe failed (<ExceptionClass>)` — class name only, never the message).
2. **`/nlsql` — `READONLY_DATABASE_URL` was never set on the api service.** The role already
   existed on prod Postgres; re-asserted grants with `tools/setup_readonly_role.py` over
   `DATABASE_PUBLIC_URL` and set the var (private-network host).
3. **`/rag` — `HF_TOKEN` never set + `narrative_embeddings` never ingested.** Applied
   `db/pgvector_setup.sql` (extension available on Railway PG 18), ingested the 2,342-row corpus
   from the local embedding cache via `app.rag.ingest.ingest_pgvector`, set `HF_TOKEN`.

## Why This Works

Each feature was built local-first with a well-behaved degrade path and shipped behind a
"prod side happens at deploy time" note. Deploy time arrived (the api's earlier import crash
was fixed) and nobody executed those notes — and because every route honors a never-500
contract, prod looked *healthy* (all 200s) while three features were down. The fixes simply
executed the deferred wiring; the added log line removes the "silent" from the next silent
degrade.

## Prevention

- **A degrade path must name its exception class in a log line.** Sanitized (class name only —
  messages can embed URIs/credentials), but never fully silent. `except Exception: return
  degraded_payload` with no logging turns a one-command diagnosis into hours.
- **Keep `requirements.txt` mechanically in sync with `pyproject.toml`** — the comment "keep in
  sync" did not work. A test pins it:

  ```python
  # apps/api/tests: requirements.txt must cover every pyproject dependency name
  import re, tomllib
  from pathlib import Path

  def test_requirements_covers_pyproject_deps():
      root = Path(__file__).resolve().parents[1]
      deps = tomllib.loads((root / "pyproject.toml").read_text())["project"]["dependencies"]
      wanted = {re.split(r"[\[<>=~!]", d)[0].strip().lower() for d in deps}
      have = {
          re.split(r"[\[<>=~!]", line)[0].strip().lower()
          for line in (root / "requirements.txt").read_text().splitlines()
          if line.strip() and not line.startswith("#")
      }
      assert wanted <= have, f"missing from requirements.txt: {sorted(wanted - have)}"
  ```

- **"Prod wiring happens at deploy time" needs an owner and a checklist row, not a prose note.**
  When a writeup defers env vars / roles / ingests to deploy time, list each item as a runbook
  step that gets checked off (the U13 runbook shape), and verify each *leg* — the kg runbook's
  "verify end-to-end" step only ever exercised the local/proxy leg, so the private-network leg
  was first exercised by a prod incident.
- **Verify the deployed environment, not just the deployed code.** `railway ssh` +
  `python3 -c "import <dep>"` and `railway variables --service <svc> --kv` answer in seconds
  what page-level probing cannot.

## Related Issues

- `docs/solutions/tooling-decisions/railway-monorepo-deploy-gotchas-2026-05-05.md` — rule 2
  (ship `requirements.txt` inside the Root Directory) is the same builder behavior; this
  learning adds the drift failure mode and the IPv6/proxy Neo4j specifics.
- `docs/writeups/kg-queries-nl-to-cypher.md` — "Postscript — the 2026-07-08 prod incident"
  narrates the three-layer diagnosis in order.
- `docs/conventions/stack.md` — env-var table and P3 section now record the completed wiring
  and the Neo4j listen-address requirement.
