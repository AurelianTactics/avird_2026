---
description: Agent perception loop over a single page — navigate, accessibility snapshot, screenshot, console-error check, compare to intent, iterate. Wraps the playwright plugin's MCP browser tools.
---

# /verify-page $ARGUMENTS

Give the agent eyes on one page. This is the **build-loop** half of the
two-layer verification model (R21): it proves a page *looks and behaves* right,
not just that it returns 200. The deterministic HTTP gate is the other half —
see `/verify-site`.

Usage: `/verify-page <route> [intent notes]`
e.g. `/verify-page /groupings "entity x severity matrix, seven columns, totals"`

This command drives the browser through the **`playwright` Claude Code plugin**
(its MCP server is already installed — no `.mcp.json` to author). First use may
need browser binaries: `npx playwright install`.

## Steps

1. **Pick a target URL.**
   - If `$ARGUMENTS` contains a full URL, use it.
   - Else treat the first token as a route path and prefix a base URL: the
     `WEB_URL` env var if set, otherwise the local dev server
     (`http://localhost:3000`). If targeting local, make sure `npm run dev` is
     running in `apps/web` first (start it if needed).
   - Everything after the route token is the **intent** — what the page is
     supposed to show. If no intent is given, infer it from the route.

2. **Navigate.** `browser_navigate` to the URL.

3. **Read the accessibility snapshot** — `browser_snapshot`. This is the
   primary, token-cheap signal: it's the rendered a11y tree as text, no vision
   model needed. Reason about structure (headings, table, links, landmarks)
   from here.

4. **Screenshot** — `browser_take_screenshot`. Use this for visual judgment the
   a11y tree can't carry: layout, density, obvious breakage, alignment.

5. **Check the console** — `browser_console_messages`. **Treat any console
   error as a finding**, even if the page rendered.

6. **Compare to intent and report a punch list.** For each expectation from the
   intent, mark it met / not met against what you observed (snapshot +
   screenshot). List console errors as findings. Show the evidence (screenshot
   path, key snapshot lines) — don't just assert "looks good".

7. **Iterate.** If findings are fixable in code, fix them, then re-run steps 2–6
   until the punch list is clean.

## What this checks vs. `/verify-site`

| | `/verify-page` (this) | `/verify-site` |
|---|---|---|
| Layer | Agent perception, **build loop** (R21) | Deterministic HTTP **gate** (R20) |
| Tooling | `playwright` plugin MCP (browser) | `tools/verify_site.py` (httpx + bs4) |
| Sees | Layout, console errors, a11y tree | Status codes, internal links, expected text |
| Cost | Tokens + a real browser | Token-free; CI / post-deploy |
| Verdict | Punch list, iterate | Hard pass/fail |

Run `/verify-page` while building a page (paired with the `frontend-design`
skill that builds it); run `/verify-site` as the gate before/after deploy. The
`ce-test-browser` and `verify` skills can drive the same MCP tools for
PR-scoped browser checks.

> Token-efficiency note: if MCP context cost grows across many pages, the
> Playwright CLI + Skills path (snapshots saved to disk as compact YAML) is the
> evolution. Chrome DevTools MCP (Chromium-only perf / Core Web Vitals) is
> reserved for later W5/W7 work — Playwright *drives*, DevTools *debugs*.
