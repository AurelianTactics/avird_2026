# Solutions

Institutional learnings: patterns, decisions, and post-incident lessons that should compound across phases. The `compound-engineering` slash commands (`/ce-compound`, `/ce-compound-refresh`, `/ce-learnings-researcher`) read and write here.

## What belongs here

Stable, reusable knowledge:

- **Bug recurrences** — "this kind of failure happened, here's how to spot and fix it next time."
- **Architecture decisions** — non-obvious shape choices an agent or future-you would otherwise have to re-derive.
- **Tooling decisions** — why a library was picked or rejected, with enough context to revisit later.
- **Conventions** — repo-specific norms that aren't already obvious from `docs/conventions/`.
- **Workflow learnings** — what worked and what didn't, when working with agents on this codebase.

One file per learning. Use frontmatter so `/ce-learnings-researcher` can match by topic.

## What does *not* belong here

- Per-phase narratives (those are in [`../writeups/`](../writeups/)).
- Stack/env-var contracts (those are in [`../conventions/stack.md`](../conventions/stack.md)).
- Active plans (those are in [`../plans/`](../plans/)).
- One-off task notes (those die with the conversation).

## Status

Empty in P0 by design — the directory exists so P1+ has a place to land learnings without inventing a convention mid-phase.
