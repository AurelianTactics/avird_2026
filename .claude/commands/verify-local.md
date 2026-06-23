---
description: The one-action local verification loop — bring up the seeded stack, drive each changed route through the browser perception loop, record evidence in .verify/, and run the deterministic gate against localhost:3000.
---

# /verify-local $ARGUMENTS

Verify changed routes end to end against the **local seeded stack** and leave
checkable evidence behind. This is the loop the Stop gate wants: it blocks
end-of-turn until every pending route has fresh passing evidence, and this
command is exactly how to produce it. Also callable any time mid-turn to
reproduce a reported bug or validate a fix — verification is a tool, not
just a gate.

Usage: `/verify-local [route ...]`
e.g. `/verify-local /groupings`, `/verify-local /incidents/[reportId]`, or
bare `/verify-local` to verify whatever the gate currently wants.

## Steps

1. **Pick target routes.**
   - If `$ARGUMENTS` lists routes, use them.
   - Else `python tools/verify_evidence.py pending-routes` — the routes the
     gate currently wants.
   - Else (no pending debt) all routes: `python tools/verify_evidence.py routes`.

2. **Ensure the stack is up.** `python tools/dev_stack.py up` (no-op when
   already running). Confirm the api line reports `db: ok`.
   - If `db: down`: **say so plainly and keep going.** A data-layer blocker
     blocks *live-data assertions only* — render, layout, console, and
     hydration checks are never excused (pages must show graceful fallbacks).
     Expect list/detail pages to render their error states instead of rows,
     and judge those states deliberately. To fix the data layer:
     `python tools/local_db_setup.py` then `python db/run_pipeline.py`
     (see docs/conventions/stack.md, "Local database").

3. **Drive each route through the perception loop** — the same steps as
   `/verify-page` (navigate → a11y snapshot → screenshot → console → compare
   to intent; see `.claude/commands/verify-page.md` for the full loop body),
   with these specifics:
   - Target `http://localhost:3000<route>`.
   - For a dynamic template (`/incidents/[reportId]`), pick the concrete
     sample URL by taking the **first detail link from the rendered list
     page** (`/`), and verify that. The evidence is keyed by the template.
   - Save the screenshot into `.verify/screenshots/` (one per route; any
     filename works — `record` just needs the path). If the browser tool
     writes elsewhere, pass its output path to `record` as-is rather than
     faking a copy.

4. **Record honest evidence per route** with
   `python tools/verify_evidence.py record --route <route> --screenshot <path> --console-errors <n> --result pass|fail [--sample-url <url>]`.
   - Pass the route **without the leading slash** (`--route about`,
     `--route incidents/[reportId]`, and `--route .` for the root route) —
     Git Bash silently rewrites leading-slash arguments into filesystem
     paths, and `record` rejects the mangled form.
   - **Findings exist → record `fail` first**, then fix, re-run step 3, and
     only record `pass` once the punch list is actually clean. The fail
     record is part of the history, not an embarrassment.
   - Console errors count as findings even when the page renders.
   - `record` refuses a screenshot path that doesn't exist — evidence
     without proof is a claim.

5. **Finish with the deterministic local gate:**
   `python tools/verify_site.py --base-url http://localhost:3000`, then
   `python tools/verify_evidence.py check` to confirm the Stop gate is
   satisfied. Print a combined punch list: per-route perception verdicts +
   verify_site results + gate state.

## Notes

- First browser use may need `npx playwright install`.
- Remote targets are out of scope here — that's `/verify-site` against the
  deployed URL (post-deploy gate). This command is the local build loop.
- `python tools/verify_evidence.py pending-clear` writes off all pending
  debt without verifying. It exists for the **user** to invoke deliberately;
  the agent never runs it silently.

## What this is vs. its siblings

| | `/verify-local` (this) | `/verify-page` | `/verify-site` |
|---|---|---|---|
| Scope | All changed routes, end to end | One page, one loop | Whole deployed site |
| Stack | Brings up local seeded stack | Assumes a server | Deployed URL |
| Evidence | Records `.verify/` artifacts the Stop gate checks | Reports in-chat | Exit code |
| When | Before ending any turn that touched pages; any time mid-turn | While iterating on one page | Post-deploy |
