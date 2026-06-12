# avird-2026

NHTSA AV crash data portfolio site. A self-directed learning project: re-exercise data engineering / EDA / ML on a real public dataset, and learn agentic + RAG patterns by building them. The build *workflow* (slash commands, hooks, evals) is itself part of the learning artifact.

**Stack:** Next.js (App Router, TypeScript) + FastAPI + Postgres 16, all on Railway.

**Current phase:** P0 — scaffold. Empty deployed substrate + compound-engineering conventions + agent-runnable site-verification harness.

## Layout

- `apps/web/` — Next.js frontend (public origin)
- `apps/api/` — FastAPI service (Railway-internal-only)
- `ontology/` — property-graph ontology pipeline over SGO narratives (LangGraph + Neo4j)
- `tools/` — repo-wide scripts (e.g. `verify_site.py`)
- `.claude/` — slash commands and hooks
- `docs/` — prose, plans, conventions, writeups, learnings

## Where to look next

- Stack snapshot, env-var contract, ports → [docs/conventions/stack.md](docs/conventions/stack.md)
- Slash commands, hooks, commit style → [docs/conventions/workflow.md](docs/conventions/workflow.md)
- Per-phase writeups → [docs/writeups/](docs/writeups/)
- Institutional learnings → [docs/solutions/](docs/solutions/)
- Active plan → [docs/plans/2026-04-28-001-feat-phase-0-scaffold-plan.md](docs/plans/2026-04-28-001-feat-phase-0-scaffold-plan.md)
- Origin brainstorm → [docs/brainstorms/nhtsa-crash-portfolio-requirements.md](docs/brainstorms/nhtsa-crash-portfolio-requirements.md)
- Ontology pipeline (env, run order, sharp edges) → [ontology/CLAUDE.md](ontology/CLAUDE.md)
- Service-local guidance: [apps/web/CLAUDE.md](apps/web/CLAUDE.md), [apps/api/CLAUDE.md](apps/api/CLAUDE.md)

## Conventions

- Conventional Commits for commit messages (advised, not enforced).
- Brief writeups land alongside code in `docs/writeups/` at the end of each phase.
- Progressive disclosure: this file stays short; depth lives in the linked docs.
