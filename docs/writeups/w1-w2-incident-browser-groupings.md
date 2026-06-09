---
phase: W1, W2
date: 2026-06-05
plan: ../plans/2026-06-05-001-feat-website-mvp-w1-w2-plan.md
---

# W1–W2 — Incident browser (raw) + groupings (treated) + agent verification

The first real surface over `treated_incident_reports`. W1 turns the P0
placeholder into a browsable incident list and per-incident one-pager over the
**raw** SGO columns; W2 adds an entity × severity matrix over the **treated**
(canonical, normalized) data. The defining split runs through every unit: the
browser shows raw reported data, the groupings page shows treated data.

## What shipped

- **Thin read-only API (3 routes).** `GET /incidents` (paginated, sortable, raw,
  **no dedup**), `GET /incidents/{report_id}` (raw one-pager + narrative, 404 on
  miss), `GET /groupings/entity-severity` (treated matrix of summed counts with
  per-entity totals). All read-only; the internal-only origin is unchanged.
- **Data-access seam (`app/data.py`).** Routes depend on an `IncidentData`
  surface via `Depends(get_incident_data)`, so route tests override it with an
  in-memory fake and run with no Postgres — the same move `test_health.py` makes
  with `check_db`. The canonical filter (`is_latest_of_multiple_report = true`)
  lives here as one constant, used **only** by the groupings query.
- **Severity normalization (`app/severity.py`).** A pure `normalize()` mapping
  raw `Highest Injury Severity Alleged` strings into seven display buckets
  (Fatality → Unknown), the single source of bucket logic for the matrix.
  Unmapped/null → `Unknown`, never dropped. The raw list never calls it.
- **Three pages + nav shell.** `/` is the new landing list (raw columns,
  clickable-header pure-text sort via URL query, server-side pagination,
  graceful empty/unreachable states); `/incidents/[reportId]` is the grouped raw
  one-pager + narrative; `/groupings` is the treated matrix. A one-line-extensible
  `Nav` shell and a minimal global stylesheet carry them. About now links the
  GitHub repo.
- **Two-layer verification.** `verify_site.py` stays the deterministic gate
  (status, links, expected text — now covering `/` and `/groupings`, with the
  detail link reached by the crawler). On top of it, the new `/verify-page`
  slash command wraps the `playwright` plugin's MCP tools (navigate → a11y
  snapshot → screenshot → console check → compare to intent) so the build loop
  can *see* a page (R21). This builds the previously-deferred R23 spike.

## Why these choices

- **Raw list shows every row — no canonical dedup (KTD 2).** A deliberate
  deviation from the origin's "canonical on lists" rule, scoped to the *list*;
  the groupings *counts* stay canonical. A test asserts the list query carries
  no dedup clause and `total` is the unfiltered `COUNT(*)`, so the deviation
  can't silently regress.
- **Pure raw-text sort behind an allow-list (KTD 4).** `sort`/`dir` map through
  fixed server-side dictionaries to quoted raw columns; the request param never
  reaches `ORDER BY`. Consequence accepted: "recent-first" is approximate (raw
  `Incident Date` is free text) and severity sorts alphabetically — noted on the
  page so it doesn't read as a bug.
- **Bucket logic in one pure function, pivoted in Python.** SQL stays simple
  (`GROUP BY master_entity, raw_severity`); the route pivots via `normalize()`,
  keeping the raw→bucket map a one-line edit.
- **Playwright plugin drives, Chrome DevTools MCP deferred.** Accessibility-
  snapshot-first (token-cheap), cross-browser, the right default for an agent
  loop. DevTools MCP (perf/CWV) is reserved for W5/W7.
- **Both plugins are agent-time only.** `frontend-design` and `playwright` add
  nothing to the shipped bundles — they're build/verify tooling (the R22
  carve-out).

## What surprised me

- **ruff B008 fired on the dependency-injected routes but not on `/health`.**
  ruff suppresses "function call in argument default" only when the parameter is
  annotated with a builtin immutable type (`db: str = Depends(...)`); a custom
  class annotation (`data: IncidentData = Depends(...)`) trips it. Fixed once,
  for the whole codebase, with `flake8-bugbear.extend-immutable-calls =
  ["fastapi.Depends"]` — the standard FastAPI+ruff setting.
- **The nav "Incidents"/"Groupings" links appear on every page**, so an `<h1>`
  heading needle isn't page-specific for the gate. Retargeted the `/` and
  `/groupings` needles to distinctive intro prose that always renders regardless
  of data state.
- **No live DB reachable from the build host** (Railway-internal-only), so the
  exact raw→bucket mapping couldn't be confirmed against real values. Built
  `normalize()` to cover the known SGO value space case-insensitively with
  unmapped → `Unknown`; confirming distinct live values stays a one-line edit.

## What's deferred

- **Live-DB confirmations** the plan flagged: exact severity raw→bucket mapping,
  whether `"Report ID"` is the right detail key, `"Reporting Entity"` vs
  `"Operating Entity"` on the list, groupings row ordering — all confirm at
  deploy against populated data.
- **The `/verify-page` browser smoke run** (against `/about`, and the U7–U9
  loops) needs a running dev server + browser binaries; it degrades to manual
  review where the browser can't launch. The deterministic gate still gates the
  build so nothing ships un-checked.
- **R6** (month/state cuts), **R7–R8** (W3 filters + drill-through — groupings
  cells stay plain text to avoid pulling it forward), and W4+ remain out of
  scope.

## Deploy / verify

Tests are green locally (api 38, tools 11, web 22). The deployed gate —
`python tools/verify_site.py --base-url <web-url>` (or `/verify-site`) — should
exit 0 once W1–W2 is deployed against populated data, and `/verify-page <route>`
closes the visual loop per page.
