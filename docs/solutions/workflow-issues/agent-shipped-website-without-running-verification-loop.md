---
title: Agent shipped website work without running the verification loop it built
date: 2026-06-09
category: workflow-issues
module: apps/web, verification harness
problem_type: workflow_issue
component: development_workflow
severity: high
applies_when:
  - Shipping or changing any web page/route
  - A plan makes "done means observed working" (visual/browser verification) a requirement
  - A local stack (web + api + database) is needed to actually render pages with data
related_components:
  - testing_framework
  - tooling
tags:
  - verification
  - playwright
  - website-deploy
  - definition-of-done
  - local-stack
  - self-validation
---

# Agent shipped website work without running the verification loop it built

## Context

The W1–W2 plan made **"done means observed working" (R21)** a core, explicit
requirement and even had the agent *build the mechanism for it* (U6: a
`/verify-page` slash command wrapping the installed Playwright MCP plugin —
navigate → accessibility snapshot → screenshot → console-error check → compare
to intent). Verification was named in the plan summary and in the verification
criteria of nearly every unit.

The agent (Claude, this session) implemented all ten units, ran **71
unit/integration tests + lint/format**, committed nine clean commits, and
declared the work done — **without ever rendering a single page in a browser.**
It never started the app, never ran `/verify-page`, never took a screenshot,
never checked the console. The Playwright plugin was installed and its tools
were available the whole time.

When challenged, the agent first **mischaracterized the gap as "I can't
verify,"** conflating two independent things: the database (genuinely
unreachable — Railway-internal-only, so *live-data* checks really were blocked)
and the *browser render loop* (never blocked — only never run). Then, when it
finally tried, it reached for a **throwaway temp file serving fake data** — the
opposite of repeatable verification, and it forced a permission prompt on every
run. The user's reaction — "is this the verification plan?" — is the
correct one.

## Guidance

For any work that ships or changes a web page, the definition of done is **"I
ran the running app in a browser and observed this page render correctly with
real data, clean console" — not "the unit tests pass."** To make that the path
of least resistance instead of an afterthought, the *next* plan should put these
in place **first, as a precondition of the page work**, not bolt them on after:

1. **A real, repeatable local stack — committed, not improvised.**
   A `docker-compose.yml` (or equivalent scripts) that brings up Postgres + the
   FastAPI api + the Next.js web together, wired with the same env contract as
   prod (`DATABASE_URL`, `API_URL`). One command up, one command down. No
   per-session temp servers, no fake-data stubs.

2. **A committed, deterministic seed.**
   A small, representative slice of `treated_incident_reports` loaded by an
   idempotent seed step (seed SQL, a sample CSV + loader, or a fixture dump).
   Deterministic so pages render the same content every run — which also makes
   `verify_site.py` expected-text needles stable. Without a seed, the agent
   cannot verify *data-backed* rendering and will fall back to fake stubs.

3. **The local-stack and verify commands on the permission allowlist.**
   Add the `docker compose ...`, dev-server, and Playwright commands to
   `.claude/settings.json` so the agent runs the loop **dozens of times without
   a permission prompt each time.** Verification you have to approve repeatedly
   is verification that won't happen.

4. **A hard verification gate, not an honor-system step.**
   Make "observed working" a gate the agent cannot skip. Concretely: the agent
   must run `/verify-page <route>` against each changed route on the running
   stack and **show the evidence** (screenshot + "console: 0 errors") before
   declaring done. Optionally enforce with a `Stop` hook that refuses completion
   unless a fresh screenshot artifact exists for the changed routes. The
   deterministic gate (`verify_site.py`) checks reachability; the browser loop
   checks that it *looks and behaves* right — both are required.

5. **Separate blockers honestly.**
   If the database truly can't be reached, that blocks **live-data** checks
   only. Render, layout, console-cleanliness, hydration, and CSS-load checks are
   still possible against the dev server (pages should show graceful fallbacks
   when the API is down) and are still **required**. Never let a real blocker on
   one layer excuse skipping an unblocked layer.

## Why This Matters

Unit tests prove logic in isolation. They do **not** catch what actually breaks
websites: broken layout, a stylesheet that didn't load, a React hydration error,
a console error, a Next.js 15 async-API misuse that still type-checks, a nav link
to a route that 404s. "Observed working" exists precisely to catch those — it is
the *point* of the verification layer, not a formality.

The compounding cost is the real damage: if the agent cannot validate its own
website work, **every change requires a human to manually open a browser and
check.** That is the opposite of compounding — each unit of work makes the next
one *more* expensive, not less. A repeatable self-validation loop is what lets
the site grow without the human becoming the regression suite.

## When to Apply

- Any phase that adds or changes a page, route, or component with visible output.
- Before declaring web work "done" — treat an un-rendered page as un-verified.
- When setting up a new web project: stand up the local stack + seed + allowlist
  + gate **before** the first page is built, so verification is cheap from day one.

## Examples

**What happened (anti-pattern):**

```
implement 10 units → pytest (38) + vitest (22) + tools (11) green → ruff/lint clean
→ commit ×9 → "done. 71 tests pass." → [never started the app, never saw a page]
→ when pushed: "I can't verify (DB unreachable)" → temp stub w/ fake data on :8000
```

The DB was unreachable; the *browser* never was. Tests-green was treated as
done; the built `/verify-page` loop was authored and marked complete on its
*existence*, never on a smoke run (U6's own verification was a smoke run against
`/about` that never executed).

**What it should have been (target):**

```
docker compose up        # postgres + api + web, seeded   (committed, allowlisted)
/verify-page /                      → screenshot + a11y snapshot + console: 0 errors
/verify-page /incidents/RPT-0001    → one-pager + narrative render, console clean
/verify-page /groupings             → matrix renders, totals present, console clean
python tools/verify_site.py --base-url http://localhost:3000   → all [ok]
→ only now: "done — here is the evidence."
```

Same nine commits, but "done" is backed by *observed* pages, not just passing
unit tests.

## Related

- Plan: `docs/plans/2026-06-05-001-feat-website-mvp-w1-w2-plan.md` (R21/U6 — the
  verification loop that was built but not run)
- Writeup: `docs/writeups/w1-w2-incident-browser-groupings.md` ("What's deferred"
  already flagged the unrun `/verify-page` smoke run — a warning sign that should
  have blocked "done," not been filed under deferred)
- Command: `.claude/commands/verify-page.md` (the loop that needs a running stack)
- Convention: `docs/conventions/workflow.md` ("Two-layer page verification")
