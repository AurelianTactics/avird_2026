---
date: 2026-06-05
topic: website-mvp
---

# AV Crash Site — Website MVP & Phase Map

## Summary

Create a browsable public site, grown page-by-page off a thin read-only API, with a clean and simple frontend that an AI coding workflow builds and verifies. The first buildable slice is an incident browser — a recent-first list that clicks through to per-incident detail — plus an entity-by-severity groupings page and an About page with a GitHub link. Later phases add filtering, findings/roadmap pages, derived visual views (contact-area and pre-crash-movement), a narrative/RAG surface, and an agent-queryable data surface. Simplicity and an agent build harness are cross-cutting constraints, not phases. This doc lays out the whole track as phases; planning picks which phases to execute.

## Problem Frame

The data engineering and EDA are done. Rich per-incident data lives in Postgres (`treated_incident_reports`: cleaned dates and coordinates, a canonical-row flag, harmonized weather/roadway, normalized `master_entity`, CP/SV contact areas and pre-crash movements, injury-severity targets, and free-text narratives). But it is only reachable through notebooks and the database — the public site is still the P0 placeholder (index + About, `api` exposing only `/health`).

This is the gap: the analysis exists, the surface to *see* it does not. The website track closes it incrementally, with each phase shipping something live and the information architecture staying emergent — pages are added as the data leads, not pre-designed. Audience is self-first; polish is bounded by "navigable in a year," not "wow a stranger in 30 seconds."

## Key Decisions
- **Simplicity is a hard constraint, not a preference.** Clean, simple, modern. YAGNI: prefer the straightforward approach that reads clearly over flexibility for futures we may not need. No speculative abstractions, frameworks, config layers, or state libraries — reach for them only when a concrete phase forces it. A page that adds indirection its phase doesn't use is a defect, not neutral.
- **The frontend is agent-built, so the build harness is part of the deliverable.** Pages are produced and reviewed through an AI coding workflow, and the project's premise is that this workflow is itself a learning artifact (see root `CLAUDE.md`). Each page must be verifiable by the site harness, and the harness grows alongside the site. This build harness is distinct from the *product* agent-queryable data surface in W7: one helps the agent build and check the site, the other lets an agent query the data.
- **Phased capture, selective build.** This doc holds the entire website track. Each phase has a clear hero and ships live. Planning executes a chosen subset (expected: W1–W2 first).
- The incident browser is the landing page. The landing page is the incidents themselves; everything else is a page added to a growing top nav. IA is emergent and additive, not designed up front.
- **Thin read-only API, not static snapshots, for v1.** The site queries `treated_incident_reports` live through a few read routes on the existing `api` service. This reuses the P0 scaffold, keeps data fresh, and leaves an agent/MCP-queryable surface open later. Static snapshots are reserved for heavily-derived pages (W5) where baking the treatment once beats querying it live.
- **Canonical incidents only on lists and counts.** The list and the groupings matrix both filter to `is_latest_of_multiple_report = true`, so multi-report incidents don't inflate rows or counts.
- **Filtering is one deferred phase, not scattered.** The first browser slice is sort + paginate only and the groupings page is read-only counts. Filters on the list and drill-through from groupings buckets land together in W3 — pulling either one forward quietly re-introduces the same server-side filter param.


## Phase Map

```
W1 Browser        W2 Groupings    W3 Filtering      W4 Findings &     W5 Derived &      W6 Narrative/    W7 Harness /
foundation        entity ×        & drill-through   roadmap pages     visual views      RAG surface      agent-native
list + detail     severity        list filters,     findings,         contact-area      talk-to-the-     MCP read
+ thin API        matrix          bucket -> list     roadmap, data     heatmap, pre-     data search      surface, site
+ About/nav                                          dictionary        crash movement    (project P3)     review harness
                                                                       redacted stats                     (project P5)

[site live and viewable at the end of every phase]
[cross-cutting, every phase: simple/readable code + agent build harness — R20–R23]
```

W1–W2 are the near-term build. W3+ are captured for planning, not built yet. W6–W7 are the website surfaces of project phases P3/P5 (see `docs/brainstorms/nhtsa-crash-project-requirements.md`) and inherit their scope rather than re-owning it.

## Requirements

**Phase W1 — Incident browser foundation**

- R1. The `api` service exposes a thin read-only surface over `treated_incident_reports`: a paginated incidents list and a per-incident detail lookup. Read-only — no write or mutation endpoints.
- R2. The landing page renders the incidents list recent-first, restricted to canonical rows, showing a column subset (default: incident date, `master_entity`, city/state, highest injury severity alleged, crash with). The list is sortable by at least date, entity, and severity, with server-side pagination.
- R3. Each list row clicks through to an incident detail subpage showing the "one-pager" field set — city/state, roadway type and description, time and date, weather, crash with, highest injury severity, property damage, CP/SV pre-crash movement, airbags deployed, vehicle towed, CP/SV contact areas, passengers belted, pre-crash speed, law-enforcement investigating — plus the incident narrative.
- R4. The About page links to the GitHub repository, and a top navigation shell links the existing pages (Incidents, About) and is structured to add later pages without rework.

**Phase W2 — Groupings**

- R5. A groupings page renders a `master_entity` × highest-injury-severity matrix: one row per entity, one column per severity bucket (Fatality, Serious, Moderate, Minor, No Injuries, Property, Unknown), each cell a summed count, with a per-entity total. Read-only, canonical rows. Severity strings are normalized from the raw `Highest Injury Severity Alleged` field into these seven display buckets.
- R6. Additional grouping cuts (incidents by month, by state) are candidates for this page or a sibling; whether W2 ships more than the entity × severity matrix is a planning decision.

**Phase W3 — Filtering & drill-through**

- R7. The landing list gains filters for the highest-value dimensions (entity, severity, state), applied server-side.
- R8. Groupings buckets become links that open the incident list filtered to that bucket (e.g. a Waymo / Serious cell opens the list scoped to those incidents).

**Phase W4 — Findings & roadmap pages**

- R9. A findings/approach page publishes early EDA takeaways ported from the notebooks: distributions over key fields, time-of-day / region / company breakdowns, incidents by month by severity, and per-entity severity rate versus the overall rate. First cut may be a prose stub before charts are ported.
- R10. A website-ideas / roadmap page renders the running ideas list as a public "where this is going" view, doubling as a roadmap for future-you and visitors.
- R11. A data-dictionary page renders from the single-source dictionary JSON (`docs/avird-sgo-database-data-dictionary/`), covering both the DB fields and the underlying source data, for humans and agents. Static for MVP; hover-to-define on incident pages is a later enhancement. Includes plain-language explanations of domain terms (e.g. ODD).

**Phase W5 — Derived & visual views**

- R12. A contact-area view visualizes CP/SV contact areas with grouping options — coarse (front / rear / side) and finer (per-area) — as a heatmap or comparable visual.
- R13. A pre-crash-movement view shows CP/SV maneuvers, optionally combined with contact areas and speeds into a simple per-incident animation shown alongside the narrative.
- R14. A redacted-narrative view shows the percent and count of redacted narratives by entity (and recently), surfacing patterns such as a single entity dominating active redactions.
- R15. Heavily-derived pages in this phase may precompute to a static snapshot at build time rather than query the API live, where the treatment is expensive or stable.

**Phase W6 — Narrative & RAG surface** (surfaces project P3)

- R16. A free-text "talk to the data" feature answers narrative questions with grounded responses citing specific incidents. Scope, eval, and infrastructure inherit project phase P3 — this phase is its website presentation, not a separate RAG build.
- R17. A clearly-labeled, opt-in reconstruction of redacted narratives from structured fields (serious or playful framing) is a stretch/fun item, contingent on P3 infrastructure.

**Phase W7 — Harness / agent-native** (surfaces project P5)

- R18. An MCP / agent-queryable read surface over the same API exposes incidents and findings as dynamic, queryable results for *external* agents — the product-side surface, distinct from the build harness in R20–R23.
- R19. A site-review harness extends the build harness toward agent-driven screenshot/audit passes that produce a punch list of issues across the whole site.

**Cross-cutting — simplicity & build harness (applies to every phase)**

- R20. Every new page and API route ships with harness verification: the site-verification harness (`tools/verify_site.py`, the `verify-site` skill) checks reachability, internal links, and expected text, and its checks grow as pages land. A phase is not done until its pages pass.
- R21. The agent build loop for any visual page is build → run the app → screenshot → check against intent → iterate. A page counts as done when observed working, not merely when it compiles.
- R22. Page and route code stays simple and readable by default — minimal dependencies, no premature abstraction, written to match the surrounding scaffold. Simplicity is a review criterion: unused flexibility is flagged, not waved through.
- R23. A research spike surveys current best practice for agent-driven frontend work — plugin tool use, MCP tool servers, and visual/screenshot verification — and records a recommendation. It informs the build loop (R21) and the W7 product surface (R18) but does not block W1. (This is the "research the state of the art later" thread from the original brief.)

## Success Criteria

- Each shipped page passes the site-verification harness (reachable, internal links resolve, expected text present).
- A new page can be built and confirmed working through the agent loop (build → screenshot → verify) with review as the only human step — no manual hand-holding to get it rendering.
- The frontend reads as clean and simple a year from now: a reader can grasp any page or route at a glance, and no abstraction exists that a shipped phase doesn't actually use.
- Every phase ends with the site deployed and the new capability visible.

## Scope Boundaries

**Deferred for later (captured as phases above, not built now)**

- Landing filters and groupings drill-through (W3).
- Findings charts, roadmap page, data-dictionary page (W4).
- Contact-area and pre-crash-movement visuals, redacted-narrative stats, static-snapshot derived pages (W5).
- Narrative search / RAG chat (W6) and the MCP / agent-queryable surface and site-review harness (W7).

**Outside this round's identity**

- No auth or accounts; anonymous public read access, consistent with the project requirements doc.
- No write or mutation endpoints — the API surface is read-only.
- No real-time data; the site reads whatever the batch-built treated table holds.
- IA is not pre-architected; the nav grows as pages land.
- Visual polish is bounded by "navigable in a year," not recruiter-facing showmanship.

## Dependencies / Assumptions

- `treated_incident_reports` is populated on Railway and exposes the columns the pages use (`incident_date`, `master_entity`, `Highest Injury Severity Alleged`, city/state, CP/SV contact areas, CP/SV pre-crash movement, `Narrative`). The repo data dictionary confirms these exist; confirm against the live DB at W1 build.
- `is_latest_of_multiple_report` reliably marks exactly one canonical row per incident — the basis for deduped lists and counts.
- The `api` service stays Railway-internal; `web` reaches it server-side via `API_URL` per the existing stack contract (`docs/conventions/stack.md`). New read routes inherit that internal-only surface.
- The raw `Highest Injury Severity Alleged` values map cleanly onto the seven display buckets after normalization; the exact source strings are confirmed at build time.

## Outstanding Questions

**Resolve before planning**

- Which phases to plan first — expected W1–W2, confirm at planning kickoff. [User decision]

**Deferred to planning**

- State-of-the-art tooling for agent-driven frontend work — plugin tool use, MCP tool servers, visual/screenshot verification — resolved by the R23 spike. Informs the build loop and W7; does not block W1.
- Final landing column subset and which columns are sortable.
- Final incident-detail field list (default is the R3 one-pager set; trim if too dense).
- Whether W2 ships only the entity × severity matrix or also by-month / by-state cuts (R6).
- Pagination size and sort interaction (column-header click vs. a sort dropdown).
- Findings page first cut: port charts or ship a prose stub (R9).
- Static-snapshot build mechanics for derived pages (R15).
