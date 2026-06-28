---
title: "feat: LLM fault judge + interactive AV-fault debate on the incident page"
type: feat
status: draft
date: 2026-06-25
---

# feat: LLM fault judge + interactive AV-fault debate on the incident page

## Summary

Recreate two LLM features from the old `AVIRD_frontend` app on the incident
detail page of the current Next.js + FastAPI + Postgres stack:

1. **LLM fault judge (precomputed)** — a neutral "insurance adjuster" LLM reads
   an incident's narrative + structured fields and returns a structured verdict
   (`is_av_at_fault`, `av_fault_percentage`, `short_explanation`). Computed
   offline in a batch over every incident row, stored in a new
   `fault_analysis` table, surfaced read-only on the incident page.
2. **Interactive fault debate (live)** — the visitor picks a side (AV at fault /
   not at fault) and argues it; an LLM advocate argues the opposite side for N
   rounds; then a neutral LLM judge reads the full transcript and renders a
   verdict. Live, stateless (the browser holds the transcript), powered by a
   LangGraph pipeline in the `api` service.

Both features hang off the existing `/incidents/{report_id}` page.

---

## Problem Frame

This is a learning project (see root `CLAUDE.md`): re-exercise data/ML/agentic
patterns on real data. The old app had both features working against a Flask-era
FastAPI + Jinja monolith with SQLite; the current stack split into a public
Next.js `web` origin, a Railway-internal FastAPI `api`, and Postgres 16, with a
LangGraph precompute track already living in `ontology/`. The job is to port the
*intent* of the two features into that architecture cleanly — not to copy the old
code, which had real flaws worth fixing on the way in.

The old code, for reference:
- Judge batch: `AVIRD_frontend/fault_analysis/get_basic_fault_fixed.py` —
  single LangGraph "arbitrator" node, JSON verdict, wrote a `fault_analysis`
  table; the page read it back (`app/main.py` `get_incident_detail`).
- Debate: `AVIRD_frontend/app/fault_analysis.py` — LangGraph (human_advocate →
  ai_advocate / judge), **in-memory `ACTIVE_SESSIONS` dict** for state.

### What we deliberately change

- **Judge stays precompute-and-store** (confirmed). Page loads stay instant, no
  LLM deps or API key in the `api` runtime for this path, and it mirrors the
  `ontology/` precompute pattern.
- **Debate stays LangGraph** (confirmed — a live learning goal). The graph/tools
  can be redesigned; it does not have to be the old graph.
- **Debate becomes stateless** (confirmed). The old in-memory session dict is
  lost on restart and breaks with >1 worker. Instead the browser holds the
  transcript and posts it back each round; the `api` runs one graph turn per
  request and persists nothing.

---

## Decisions locked

| # | Decision | Choice |
|---|----------|--------|
| D1 | Judge compute model | Precompute batch → `fault_analysis` table → read route → page |
| D2 | Debate framework | LangGraph in the `api` service (new graph OK) |
| D3 | Debate state | Stateless — client holds transcript, posts it each turn |

### Defaults chosen (call out if you disagree)

- **Provider/model:** Anthropic Claude, consistent with `ANTHROPIC_API_KEY`
  already in the env contract and the ontology track. Default `claude-haiku-4-5`
  for both advocate turns and the judge (fast + cheap); model id stays
  configurable via env so the judge can be upgraded later.
- **Batch judge env:** reuse the existing ontology sidecar env
  (`avird-2026-ontology`, Python 3.12) — it already pins `langgraph` +
  `langchain-anthropic` and loads `DATABASE_URL`. Avoids a third venv.
- **No filter — judge every row.** The old `automation_system_engaged = 'ADS'`
  filter is dropped. The batch judges **every** incident row in
  `treated_incident_reports` (~3,120 rows before dedup; a cheap Haiku batch).
  This is a for-fun feature, not an analysis claim — no need to justify a subset.
  Expect inconsistent verdicts across multiple reporting rows of the *same*
  incident (same crash, different reporter → possibly different verdict); that is
  acceptable and handled by a UI disclaimer (R5a), not by deduping.
- **`report_id`:** the treated table's `"Report ID"` column.

---

## Requirements

### Feature 1 — LLM fault judge (precompute + display)

- **R1.** A new `fault_analysis` table stores one verdict per `(report_id,
  fault_version)`: `is_av_at_fault BOOLEAN`, `av_fault_percentage NUMERIC(5,4)
  CHECK 0..1`, `short_explanation_of_decision TEXT`, `model TEXT`, `created_at`.
  Idempotent on the unique key; re-running a version upserts, a new version
  appends. Created via the existing `db/sql/*.sql` + `create_tables.py` runner.
- **R2.** A batch script formats **every** incident row and runs a LangGraph
  single-node neutral-adjuster graph that returns the structured verdict as JSON.
  The LLM prompt includes the **narrative plus key structured columns** (not the
  narrative alone) — e.g. operating entity, date/time, city/state, crash-with,
  pre-crash movements (SV + CP), pre-crash speed, posted speed, roadway type,
  lighting, weather, injury severity, property damage (porting the old
  `format_incident_for_llm` field set, mapped to the treated column names; the
  exact list lives in `fault/format.py`). Output is validated (bool, float in
  [0,1], bounded-length string) before write; parse failures store an explicit
  error sentinel, never a guessed value.
- **R3.** LLM calls are content-addressed cached (sha256 of rendered prompt +
  model id, one JSON file per call), mirroring the ontology cache so re-runs pay
  only for misses. `--limit` and `--dry-run` flags for cheap iteration.
- **R4.** The `api` exposes the stored verdict read-only (no LLM deps added to
  the `api` runtime for this path). Surfaced either as a `fault` block on
  `GET /incidents/{report_id}` or a sibling `GET /incidents/{report_id}/fault`.
- **R5.** The incident page renders the verdict (at-fault yes/no, fault %,
  explanation, model + version footnote) and degrades gracefully when no verdict
  exists for that report.
- **R5a. Disclaimer (in scope).** Both LLM features carry a visible disclaimer:
  this is an AI opinion for entertainment/learning, not a legal or factual
  determination, and the same real-world crash can get different verdicts across
  its separate reporting rows. Shown near the fault verdict and the debate panel.

### Feature 2 — Interactive fault debate (live, stateless, LangGraph)

- **R6.** The `api` runs a LangGraph debate pipeline at runtime with two
  stateless operations:
  - **advocate turn** — input `{report_id, user_position, transcript,
    user_argument}` → output one AI advocate message arguing the *opposite*
    side, using incident data the `api` looks up itself by `report_id`.
  - **judge verdict** — input `{report_id, transcript}` → output a neutral
    verdict `{is_av_at_fault, fault_percentage, reasoning}`.
- **R7.** No server-side session store. State lives in the client; every request
  carries the transcript. The `api` validates and bounds every request (max
  rounds, per-message length, total transcript size) and persists nothing.
- **R7a. Caps + budget guard (in scope, not optional).** Because the debate
  routes are reachable from the public `web` origin and bill paid LLM calls,
  enforce hard caps at both the `web` proxy and the `api`: max rounds per debate,
  max characters per argument, max total transcript size. Add a **dollar budget
  guard** in the `api`: track estimated USD spend per rolling 24h window from
  each call's token usage × the Haiku price, and once the window exceeds the cap
  return a 429 with a friendly "AI debates are taking a break — try later"
  message. **Default cap: `$5`/day**, override via `DEBATE_DAILY_BUDGET_USD`.
  (Per-IP limiting is a possible later add; the global dollar guard is the
  must-have. The guard is process-local — good enough for a single small `api`
  instance; note it resets on restart.)
- **R8.** Because the browser cannot reach the internal `api`, `web` exposes thin
  **route handlers** (`app/api/incidents/[reportId]/debate/turn` and
  `.../judge`) that proxy browser calls to the internal `api` via server-only
  `API_URL`. Same validation/caps enforced at the proxy.
- **R9.** A client component on the incident page drives the flow: pick a side →
  argue (textarea, length-capped) → see AI rebuttal → repeat up to N rounds →
  "Request verdict" → render the judge's decision. Round counter + clear
  loading/error states. Works without the precomputed judge present.

### Cross-cutting

- **R10.** `ANTHROPIC_API_KEY` becomes a runtime secret for the `api` service
  (new — previously only ontology scripts used it). Documented in
  `docs/conventions/stack.md` env-var contract.
- **R11.** Tests run with no network and no key: the LLM client is stubbed in
  `api` route tests and the batch unit tests (the ontology track's existing
  pattern). Web route handlers + the debate component are tested with mocked
  fetch.
- **R12.** The incident **route** passes the project's verification gate
  (`/verify-local`) — we verify the *page template's distinct states*, **not
  every incident**: a handful of representative `/incidents/{id}` URLs covering
  (a) verdict present, (b) verdict absent, (c) the debate panel round-trip, and
  (d) the DB-down fallback. Fresh `.verify/` evidence for those states only.

---

## Proposed Architecture

```
Browser ──> web (public, Next.js)
              ├─ incident page (server component): reads stored fault verdict via API_URL
              ├─ DebatePanel (client component): holds transcript in React state
              └─ route handlers /api/incidents/[id]/debate/{turn,judge}  ──> api (internal)
api (internal, FastAPI)
   ├─ GET  /incidents/{id}            (existing; + fault block)  ── reads fault_analysis
   ├─ GET  /incidents/{id}/fault      (read-only verdict)        ── reads fault_analysis
   ├─ POST /incidents/{id}/debate/turn   (LangGraph advocate)    ── live LLM, stateless
   └─ POST /incidents/{id}/debate/judge  (LangGraph judge)       ── live LLM, stateless
fault/ (offline batch track, ontology sidecar env)
   └─ judge_batch.py ── LangGraph adjuster ── writes fault_analysis
db: treated_incident_reports (existing) + fault_analysis (new)
```

### New / changed files (sketch)

**DB**
- `db/sql/005_fault_analysis.sql` — new table DDL.
- `db/create_tables.py` — add `005_*` to `create()` (and drop in `099_drop_all.sql`).
- `db/tests/test_create_tables.py` — assert the new table is created.

**Batch judge (Feature 1)**
- `fault/judge_batch.py` — load ADS incidents, run graph, validate, cache, write.
- `fault/format.py` — incident row → adjuster prompt (port of the old field map).
- `fault/graph.py` — single-node LangGraph adjuster (JSON verdict).
- `fault/tests/test_format.py`, `fault/tests/test_judge_batch.py` — stubbed LLM.
- `fault/CLAUDE.md` — thin index (env, run order, sharp edges), mirroring `ontology/CLAUDE.md`.

**API (Features 1 read + 2 live)**
- `apps/api/app/fault.py` — `fetch_fault(report_id)` data accessor + read route.
- `apps/api/app/debate.py` — LangGraph advocate/judge graphs + the two POST routes; LLM client behind a dependency that tests override.
- `apps/api/app/incidents.py` — fold the fault block into `_shape_detail` (or keep separate route).
- `apps/api/app/main.py` — `include_router(fault.router)`, `include_router(debate.router)`.
- `apps/api/pyproject.toml` + `requirements.txt` — add `langgraph`, `langchain-anthropic` (keep in sync per the Railway nested-deploy note).
- `apps/api/tests/test_fault.py`, `test_debate.py` — fake data layer + stubbed LLM.

**Web**
- `apps/web/app/lib/api.ts` — `FaultVerdict` type + `fetchFault` (or extend `IncidentDetail`).
- `apps/web/app/incidents/[reportId]/page.tsx` — render the fault block + mount `DebatePanel`.
- `apps/web/app/incidents/[reportId]/DebatePanel.tsx` — client component (transcript state, rounds, verdict).
- `apps/web/app/api/incidents/[reportId]/debate/turn/route.ts` + `.../judge/route.ts` — proxy to internal `api`.
- `*.test.tsx` for the panel + handlers.

**Docs**
- `docs/conventions/stack.md` — add `ANTHROPIC_API_KEY` (api runtime) + new routes to the API contract.

---

## Validation

How we prove each piece works. Nothing is "done" on the strength of tests alone —
the web surfaces must be *observed* working per the project's verification gate
(`apps/web/CLAUDE.md`).

### Automated (run with no network, no API key)

The LLM client is **stubbed** everywhere in automated tests (the ontology
track's existing pattern), so the suite is deterministic and free to run.

- **DB** (`db/tests/test_create_tables.py`): after `create(engine)`, the
  `fault_analysis` table exists with the right columns + the `0..1` check
  constraint; re-running `create()` is idempotent; `099_drop_all.sql` drops it.
- **Batch judge** (`fault/tests/`):
  - `test_format.py` — incident row → prompt text includes the narrative and the
    expected structured fields; missing/blank columns are skipped, not rendered
    as "None".
  - `test_judge_batch.py` — with a stub LLM returning canned JSON, a verdict row
    is written with the parsed values; **malformed JSON / out-of-range
    percentage / wrong types produce the error sentinel, never a guessed value**;
    a second run with the same `(report_id, fault_version)` upserts (no dupes);
    the content-addressed cache returns the cached call on re-run (0 new LLM
    calls).
- **API read route** (`apps/api/tests/test_fault.py`): with a fake data layer,
  `GET /incidents/{id}/fault` returns the stored verdict; a report with no
  verdict returns 404 (or an explicit `null` block — pick one and assert it);
  the detail route still works when no verdict exists.
- **API debate routes** (`apps/api/tests/test_debate.py`): with a stub LLM,
  `POST .../debate/turn` returns one advocate message arguing the *opposite*
  side; `POST .../debate/judge` returns a validated verdict; **over-cap inputs
  (too many rounds, oversize argument/transcript) are rejected with 4xx**; once
  the budget guard's window cap is hit, further calls return **429** (drive this
  with a low cap injected in the test, stub LLM — asserts the guard, spends
  nothing).
- **Web proxy handlers** (`*.test.tsx`, mocked `fetch`): `turn`/`judge` handlers
  forward to `API_URL`, enforce the same caps before proxying, and map upstream
  4xx/429/5xx to sane client responses; `API_URL` never leaks to the client
  bundle.
- **Web components** (`*.test.tsx`): the fault block renders verdict + disclaimer
  and the graceful empty state; `DebatePanel` walks pick-side → argue → rebuttal
  → verdict against a mocked handler, enforces the round cap in the UI, and shows
  loading/error states.

Gate per service: `apps/api` → `pytest` + `ruff check . && ruff format --check .`;
`db` → `pytest`; `apps/web` → `npm test` + `npm run lint`. The `/ship` skill runs
the lint+format+test gate for both apps.

### Manual / observational (the real "done")

- **Batch judge smoke run:** `--dry-run` first (no DB writes, no spend beyond the
  cache), then `--limit 5` against the **local seeded DB**, then inspect the 5
  rows in `fault_analysis` by eye for sane verdicts before any full run.
- **`/verify-local` evidence (required, R12):** bring up the seeded local stack
  and drive a **few representative** `/incidents/{reportId}` URLs (not all of
  them) through the perception loop, capturing fresh `.verify/` evidence
  (screenshot + console-error count + content hashes) for these four states:
  1. an incident **with** a stored verdict — fault block renders correctly;
  2. an incident **without** a verdict — graceful empty state, no console errors;
  3. the **debate panel** — a full pick-side → argue → rebuttal → verdict round
     trip against the live local stack (this spends a few real Haiku calls
     locally — expected);
  4. **DB-down / api-unreachable** fallback on the page (render + console
     cleanliness must still pass; only live-data assertions are excused).
- **Deployed check:** after Railway deploy, `/verify-site` against the public web
  URL confirms the page renders and the debate round-trip works end to end
  through the real `web → api` internal hop.

### Acceptance criteria

- ✅ Every incident page either shows a fault verdict + disclaimer or a clean
  empty state — never a crash or a raw error.
- ✅ A full debate round-trip (pick side → ≥1 rebuttal → verdict) works locally
  and on the deployed site.
- ✅ Caps reject oversize input and the budget guard returns 429 once tripped
  (proven by test).
- ✅ Full test + lint gate green for `db`, `apps/api`, `apps/web`.
- ✅ Fresh `.verify/` evidence exists for the four page states above.

---

## Human setup steps (genuinely human-only)

Short list — only secrets and authorizing spend. Everything else (creating the
`fault_analysis` table, running the local stack, `--dry-run`, tests, verify
evidence) the agent does itself.

**Verified current state** (checked this session, so it's not guessed):
Postgres **is** running on `localhost:5432` and `avird_dev` is set up — the agent
just needs the password. This working copy has **no `.env`** (gitignored / absent
here), and the ontology sidecar env already exists with `langgraph` +
`langchain-anthropic`.

### Phase A

1. **Provide secrets in the root `.env`** (the only blocker for the agent to
   touch the DB and for the batch to call Anthropic). Create `.env` at repo root
   with your real local Postgres password and Anthropic key:
   ```
   DATABASE_URL=postgresql://postgres:<your-local-pw>@localhost:5432/avird_dev
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   That's it — no need to seed the DB (already seeded) or create the env (exists).
   The agent then creates the `fault_analysis` table itself (runs the migration).
2. **Run the paid batch** when the agent says it's ready (you authorize the
   spend; the agent will have already run `--dry-run` + tests). Estimated cost:
   ~3,120 Haiku calls ≈ a few dollars, less on cache hits.
   ```bash
   source ~/claude_code_repos/my-uv-envs/avird-2026-ontology/.venv/Scripts/activate
   python fault/judge_batch.py --limit 5            # eyeball 5 rows first
   python fault/judge_batch.py --fault-version mvp_0.01   # full run
   ```

### Phase B (Railway)

3. **Add `ANTHROPIC_API_KEY` to the `api` service on Railway** (new — `api` was
   key-free). Dashboard: `avird-2026` → **`api` service → Variables → New
   Variable** → `ANTHROPIC_API_KEY` → deploy. **Do not** add it to `web`. No new
   service or `API_URL` change is needed; the debate routes live in the existing
   `api`. Budget/cap env vars (`DEBATE_DAILY_BUDGET_USD` default `$5`, etc.) ship
   with code defaults — only set them on Railway if you want different limits.

### Later

4. **Re-run the batch after a data re-seed** — new incidents have no verdict until
   you do. Idempotent + cache-backed, so it only bills genuinely new rows.

---

## Risks & Open Items

- **Paid LLM calls on a public surface.** The debate route handlers are public.
  Addressed by R7a (in scope): hard caps + an `api`-side budget guard land with
  Phase B before exposure. Per-IP rate limiting remains a possible later add.
- **`api` runtime now needs `ANTHROPIC_API_KEY`.** New secret on a service that
  was previously key-free. Railway env addition + stack.md update required.
- **Adding LangGraph to the `api` image** increases build size / cold start.
  Acceptable given D2; note it and measure. (If it ever bites, the advocate/judge
  are simple enough to fall back to the raw `anthropic` SDK without changing the
  route contract.)
- **Verdict freshness.** Precomputed verdicts go stale if the treated data is
  re-seeded with new incidents; re-running the batch (idempotent) is the answer.
  New ADS incidents simply show no verdict until the next batch run.
- **Verification gate.** Per `apps/web/CLAUDE.md`, page-affecting edits can't end
  a turn without `/verify-local` evidence; budget time for the perception loop on
  the incident page, including fallbacks.

---

## Suggested phasing

- **Phase A — Feature 1 (fault judge), end to end and shippable on its own.**
  DB table → batch judge (run with `--limit` first) → api read route → page
  render + graceful empty state → verify. **Human steps 1–2** (secrets in
  `.env`; authorize the paid batch — agent runs the migration + `--dry-run`).
- **Phase B — Feature 2 (debate).** api LangGraph + stateless routes (stubbed-LLM
  tests) → web proxy handlers → DebatePanel → caps + $5/day budget guard →
  verify. **Human step 3** (Railway `ANTHROPIC_API_KEY` on `api`).

Each phase is independently mergeable; Phase A carries the smaller blast radius
(no new `api` runtime deps) and proves the data + display path before the live
path lands.
