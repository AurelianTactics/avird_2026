---
title: "feat: EDA phase closeout — agent context + point-in-time report"
type: feat
status: active
date: 2026-05-31
origin: docs/brainstorms/nhtsa-crash-project-requirements.md
---

# feat: EDA phase closeout — agent context + point-in-time report

## Summary

Close out the EDA phase by harvesting the findings currently scattered across 9 notebooks, ~17 `eda_utils_*.py` modules, three track plans, two reviews, and several scrap notes — processing them **once** into a working inventory, then splitting that inventory by durability into two deliverables. (1) A **durable agent-context layer**: a thin `eda/CLAUDE.md` index plus an on-demand findings/decisions file under `eda/context/`, deliberately excluding volatile point-in-time stats so agents are not anchored to numbers that will move on the next data refresh. (2) A **point-in-time EDA report notebook** (off-site, repo-resident, exported to frozen dated HTML) that is the rich superset — main steps, curated interesting findings, the single central "what was and wasn't tried" coverage log, links out to notebooks/GitHub/docs for the deep stuff not worth showing inline, and next-step sparks. Backlog and unfinished plumbing (including the `06_eda_clean_up_summary.ipynb` orchestration TODOs) are summarized as deferred, not built.

---

## Problem Frame

The EDA work in `eda/ADS_to_2026_03_16/` is effectively complete — `eda_to_do.md` is almost entirely `DONE` across the initial-explore, target, treatment, and NLP tracks — but the *knowledge* it produced is fragmented. Findings live inside notebook cells, util docstrings, artifact CSV/PNGs, per-track plans (`docs/plans/`), reviews (`docs/reviews/`, `docs/code-reviews/`), and loose notes (`embeddings_notes.md`, `private/scratch_plans/narrative_ontology.md`, the `DONE` lines of `eda_to_do.md`). Two consequences: a future agent (or future-you) re-derives context every session, and there is no single human-readable account of what this phase actually found and tried. The existing `eda/context/` dir holds schema reference (`columns.txt`, `column_dtypes.csv`, `value_counts/`, `data_dictionary.md/.csv`) but **no synthesized findings**, and `eda/CLAUDE.md` is conventions-only — this is exactly the gap the "Improve Agent context" section of `eda_to_do.md` flags. This closeout supports the project's Phase 1 deliverable intent (baseline EDA + data dictionary published, and a candid account of the AI-augmented workflow) without yet building the deployed-site surfaces (see origin: `docs/brainstorms/nhtsa-crash-project-requirements.md`, R12/R13/R17).

---

## Requirements

- R1. A durable agent-context layer exists with progressive disclosure: a thin `eda/CLAUDE.md` index pointing at on-demand files, plus a findings/decisions doc under `eda/context/` that captures only the *durable* subset (schema gotchas, pipeline decisions, target choices, redaction patterns) and deliberately excludes volatile point-in-time statistics. Closes the "Improve Agent context" items in `eda_to_do.md`.
- R2. A point-in-time EDA **report notebook** (off-site, repo-resident) consolidates: data overview, main steps taken, curated interesting findings, and the single central "what was and wasn't tried" coverage log — with links out to notebooks/GitHub/docs for deep material not worth rendering inline. (Supports origin R13, R17.)
- R3. Findings are processed **once** into a working inventory, then split by durability — durable subset → agent context (R1); full set incl. transitory/interesting/idea-sparks → report (R2) — so there is one harvest feeding two curated outputs. (Satisfied across U1 → U2 → U3; "done" when both outputs are written from the single U1 inventory.)
- R4. The report is exported to a **frozen, dated** HTML artifact committed in the repo (point-in-time snapshot).
- R5. Backlog and unfinished work (including the `06_eda_clean_up_summary.ipynb` orchestration TODOs) are summarized and clearly marked deferred — not built in this phase.

**Origin acceptance trace:** origin R4/R8 (progressive-disclosure `CLAUDE.md` convention) are continued by the agent-context layer (U2). Origin R12 (data dictionary) is already satisfied by `eda/context/data_dictionary.md/.csv`; this plan references it rather than rebuilding it. Origin R13 (baseline EDA published) and R17 (candid writeup of where AI tools helped vs. misled) are advanced here as a repo-resident report; on-site publishing is deferred to the website phase.

---

## Scope Boundaries

- No Next.js / FastAPI / Postgres / Railway / deploy work. The report is **off-site and repo-resident** (notebook + HTML in git).
- No **new** analyses — **harvest and curate only** from existing notebooks, utils, and artifacts. (Re-rendering an existing chart in the report env, or computing a light chart live from the already-cleaned `df`, is curation, not new analysis; re-running heavy pipelines at export time is out.)
- The agent-context findings doc is **not** anchored to volatile point-in-time statistics; durable structure/decisions/caveats only.
- No building the interactive website ideas listed under the `eda_to_do.md` "Website" section (dynamic heatmaps, filter boxes, etc.).

### Deferred to Follow-Up Work

- Publish the report (or successor interactive EDA pages) to the deployed site — website build phase.
- Finish the `06_eda_clean_up_summary.ipynb` cleanup orchestration (`is_latest_of_multiple_report`, full step pipeline, created-columns manifest) — data-ingestion phase. Summarized here, not executed.
- Backlog items enumerated in `eda_to_do.md` (NLP follow-ups, better targets, incremental-analysis skill, etc.).

---

## Context & Research

### Relevant Code and Patterns

- `eda/context/` + `eda/context/_build_context.py` — existing reusable-context dir and its rebuilder; new findings file slots in alongside `data_dictionary.md` and is referenced from `README.md`.
- `eda/context/README.md` — documents the context files; update to list the new findings/decisions doc and agent-check file.
- `eda/CLAUDE.md` — currently conventions-only; becomes the thin index entrypoint.
- `private/scratch_plans/context_ideas.md` — already worked out the target pattern (thin entrypoint + on-demand files, `@`-import sparingly, a "Claude answers without re-reading the PDF" verification set). Use it as the design source for U2.
- The 9 notebooks under `eda/ADS_to_2026_03_16/` + `eda_utils_*.py` modules + existing `artifacts_*/` — the harvest surface for U1 and the chart source for U3 (reuse, don't re-derive).
- `eda/ADS_to_2026_03_16/06_eda_clean_up_summary.ipynb` — note: this is a data-cleanup/orchestration notebook with open TODOs, **not** a findings summary; its state is documented as deferred (R5), not finished here.

### Institutional Learnings

- `docs/solutions/architecture-patterns/narrative-embeddings-pipeline-2026-05-18.md` — prior synthesized learning; a model for the durability and tone of the findings doc, and a candidate "deep link" target from the report.

### External References

- Origin brainstorm `docs/brainstorms/nhtsa-crash-project-requirements.md` (R4 progressive-disclosure CLAUDE.md; R13/R17 deliverable intent).

---

## Key Technical Decisions

- **One harvest, two curated outputs (report notebook = superset, agent doc = durable subset).** The report notebook intentionally carries transitory/interesting findings and idea-sparks (the user wants a central place for "what was and wasn't tried"); the agent doc takes only what survives a data refresh. Rationale: agents should not be anchored to point-in-time numbers, but humans benefit from the full account. (Terminology: "report notebook" = the U3 `.ipynb`; "HTML report" = the U4 frozen export.)
- **Findings doc is an on-demand `eda/context/` file, referenced from the `CLAUDE.md` index — not `@`-imported.** Keeps baseline per-turn token cost low; the index tells the agent when to read it (per `context_ideas.md` analysis).
- **Single Python 3.12 report env; curated chart assets committed.** Build/reuse one 3.12 env carrying matplotlib + LightGBM/SHAP + spaCy (`en_core_web_lg`) so the report notebook runs in a single env (the main 3.14 env lacks these wheels). Un-gitignore and commit only the **curated images the report actually embeds** (a `report_assets/` set) — not the full artifact sprawl the user flagged in `eda_to_do.md` — so "harvest, don't re-derive" is literally true and the HTML report is self-contained and frozen.
- **HTML report exported static, frozen and dated.** SGO data refreshes periodically; a point-in-time snapshot must be explicitly time-stamped so it is never mistaken for current.
- **Working inventory (U1) is a scratch artifact in `private/scratch_plans/`, not a deliverable.** It is the processing step the user asked for ("start with findings and process, then build to the parts of interest"); it is not maintained after the two outputs are written.

---

## Open Questions

### Resolved During Planning

- Notebook destination: **off-site, repo-resident** (user decision). No deploy/site integration this phase.
- Does the report duplicate the coverage log already in `eda_to_do.md`? It **consolidates and supersedes** the scattered version as the single readable account, and links back to `eda_to_do.md` for the raw backlog. User explicitly wants one central place.
- `06` cleanup orchestration: **out of scope**, documented as deferred (user decision).
- Report chart strategy: run the notebook in a **single Python 3.12 report env** (matplotlib + LightGBM/SHAP + spaCy); **un-gitignore and commit the curated `report_assets/` images** the report embeds so charts are harvested, not re-derived on every export (user decision: "use a 3.12 env… don't gitignore artifacts"). The 3.14-env wheel gap and gitignored-artifacts friction is resolved, not a design fork.

### Deferred to Implementation

- Exact filename/number for the report notebook (e.g., `00_eda_report_2026.ipynb` vs `07_...`) — pick during U3 to fit the existing numbering without colliding.
- Which specific charts/artifacts are "interesting enough to show inline" vs. "link out" — decided while curating in U3 against the U1 inventory.
- Final section list of the durable findings doc (`eda/context/findings.md`, name committed) — settle the section breakdown in U2.

---

## Implementation Units

### U1. Harvest and process scattered findings into a working inventory

**Goal:** Produce a single working inventory of everything this EDA phase tried and found, tagged by durability and "worth showing," to feed both downstream outputs.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Create: `private/scratch_plans/eda_findings_inventory.md` (scratch, not a maintained deliverable)

**Approach:**
- Sweep the harvest surface: the 9 notebooks under `eda/ADS_to_2026_03_16/`, `eda_utils_*.py` docstrings, `artifacts_*/` outputs, the three `docs/plans/` track plans, `docs/reviews/` + `docs/code-reviews/`, `embeddings_notes.md`, `private/scratch_plans/narrative_ontology.md`, and the `DONE`/backlog lines of `eda_to_do.md`.
- For each finding capture: short description, key result, **durability tag** (durable structure/decision/caveat vs. volatile point-in-time stat), where it lives (notebook/util/artifact path), and a **show-inline vs. link-out** tag.
- Explicitly list the known durable anchors so they aren't lost: old-vs-new SGO schema split, compound-vs-simple airbag/towed columns, narrative `--- next report ---` separator polluting sentence segmentation, `Engagement Status` (new) vs `Automation System Engaged?` (old) mapping, `master_entity` grouping choice, the dedupe rule, treatment passes, targets kept (`Injury Reported`, `SV Speed >= 15`), and narrative-redaction pattern (Tesla recent/active).

**Patterns to follow:**
- `private/scratch_plans/` working-notes convention (`scratch_plans_readme.md`).

**Test scenarios:**
- Test expectation: none — scratch processing artifact, no behavioral change.

**Verification:**
- Every `DONE` track in `eda_to_do.md` and every `docs/plans` + `docs/reviews` entry is represented by at least one inventory row, each carrying a durability tag and a show/link tag.

---

### U2. Durable agent-context layer (progressive disclosure)

**Goal:** Give a future agent (and future-you) a thin entrypoint plus an on-demand durable findings/decisions file, so context is not re-derived each session and is not anchored to volatile stats.

**Requirements:** R1, R3

**Dependencies:** U1

**Files:**
- Modify: `eda/CLAUDE.md` (restructure into a thin explicit index)
- Create: `eda/context/findings.md` (durable findings/decisions/caveats — name committed)
- Create: `eda/context/agent_check.md` (5–10 domain questions an agent should answer from context without re-reading the PDF)
- Modify: `eda/context/README.md` (list the two new files)

**Approach:**
- Rewrite `eda/CLAUDE.md` as a thin index: keep the run/env + "add a function to `eda_utils_x.py`" conventions, then add an explicit "if the user asks about X, read `./context/Y`" map covering `data_dictionary.md`, `columns.txt`/`column_dtypes.csv`, `value_counts/`, the new `findings.md`, and the point-in-time report from U4.
- `findings.md` carries only the **durable** rows from the U1 inventory: schema gotchas, pipeline/dedupe/treatment decisions, target choices and why, redaction patterns, key data caveats. No volatile point-in-time numbers; where a number is illustrative, mark it as point-in-time and link to the report rather than restating it as fact.
- `agent_check.md` is the lightweight verification set from `context_ideas.md` — questions whose answers prove the context is sufficient.

**Patterns to follow:**
- `private/scratch_plans/context_ideas.md` (thin entrypoint + on-demand, `@`-import sparingly).
- Existing `eda/context/README.md` structure.

**Test scenarios:**
- Integration (agent-context check): a **manual, judgment-based spot-check** (run by the author or an agent in a fresh session scoped to `eda/`) — the questions in `agent_check.md` are answerable from `CLAUDE.md` + the linked `context/` files **without** opening the source PDF or a notebook. This is a qualitative pass/fail, not an automated gate; any question that forces a PDF/notebook read is a gap to fix in `findings.md`.
- Edge case: `findings.md` contains no bare volatile statistic presented as durable fact (point-in-time figures are marked and link to the report).

**Verification:**
- `eda/CLAUDE.md` is a skimmable index (no inlined heavy content) and names every `context/` file including `findings.md` and the report.
- The `agent_check.md` questions pass the fresh-session read-test above.

---

### U3. Point-in-time EDA report notebook (central artifact)

**Goal:** Build the single human-facing account of the phase — main steps, curated interesting findings, the central "what was and wasn't tried" coverage log, links out, and next-step sparks.

**Requirements:** R2, R3, R5

**Dependencies:** U1, U2 (verification cross-checks durable claims against U2's `findings.md`)

**Files:**
- Create: `eda/ADS_to_2026_03_16/<NN>_eda_report_2026.ipynb` (number chosen to avoid collision; `<NN>` is a placeholder resolved in this unit — `01`–`06` are taken)

- **Prerequisite — make chart assets present:** in the single 3.12 report env, regenerate (or locate) the specific images the report will embed, un-gitignore them, and commit the curated subset under `eda/ADS_to_2026_03_16/report_assets/`. Light charts (distributions, heatmaps from the cleaned `df`) may instead compute live in the same env; heavy visuals (LightGBM/SHAP, spaCy/displaCy, embeddings) are embedded as committed images so the export does not re-run them.
- Sections: (1) Data overview (sources, row counts, old/new schema split); (2) Main steps taken (dedupe → treatment → targets → topics/NLP → embeddings/spaCy), each a short paragraph linking the owning notebook/util; (3) Interesting findings, charts sourced per the prerequisite above (committed images for heavy visuals, optional live compute for light ones — no re-deriving heavy pipelines at export time); (4) The central coverage log — "what was and wasn't tried," consolidating `eda_to_do.md` `DONE`/backlog + per-track plans/reviews, including a candid where-AI-helped-vs-misled note (origin R17); (5) Backlog & deferred summary (incl. the `06` cleanup TODOs) marked clearly as not-done; (6) Next-step sparks.
- Anything not worth rendering inline gets a link to the notebook / GitHub / `docs/` entry rather than a re-run.
- Header cell states the snapshot date and that it is point-in-time.

**Patterns to follow:**
- Existing notebook setup preamble (`sys.path.append('..')`, `autoreload`, `eda_utils_*` imports) as in `06_eda_clean_up_summary.ipynb` / `06_eda_target_injury_2026.ipynb`.

**Test scenarios:**
- Happy path: the notebook executes top-to-bottom in the 3.12 report env, no cell errors; every committed `report_assets/` image resolves and every live-computed chart renders.
- Edge case: every deferred/backlog item referenced is marked as not-done (no implied completion); every "link out" reference resolves to an existing path/URL.

**Verification:**
- Notebook runs clean end-to-end; the coverage log is the single consolidated account and links back to `eda_to_do.md` for raw backlog; durable claims are consistent with `eda/context/findings.md` from U2.

---

### U4. Freeze and export the report

**Goal:** Produce the committed, dated, point-in-time HTML snapshot and wire it into the agent index.

**Requirements:** R4

**Dependencies:** U2, U3 (U4's `CLAUDE.md` edit must land on top of U2's restructured index)

**Files:**
- Create: `eda/ADS_to_2026_03_16/<NN>_eda_report_2026.html` (exported snapshot; same `<NN>` chosen in U3)
- Modify: `eda/CLAUDE.md` (add the report location to the index)

**Approach:**
- Execute the U3 notebook fresh in the 3.12 report env, then export to HTML (e.g., `jupyter nbconvert --to html --execute`) so the snapshot reflects a clean run; committed `report_assets/` images are embedded, heavy pipelines are not re-run.
- Confirm the HTML carries the snapshot date; add a one-line pointer in the `CLAUDE.md` index ("point-in-time EDA report: `<path>.html`").

**Patterns to follow:**
- N/A (standard nbconvert export).

**Test scenarios:**
- Happy path: HTML export succeeds from a clean execute, opens in a browser, and renders the charts and coverage log.
- Edge case: the snapshot date is visible in the rendered HTML.

**Verification:**
- A dated HTML report is committed; the `CLAUDE.md` index points at it.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Report notebook drifts from durable agent doc (two accounts disagree) | Single U1 harvest feeds both; U3 verification checks durable claims against `findings.md`. |
| Scope creep into re-running/extending analyses or website features | Scope Boundaries forbid new analysis and site work; U3 is harvest-and-curate, heavy charts embedded as committed images. |
| Findings doc bloats with volatile stats and ages badly | Durability tagging in U1; U2 edge-case check rejects bare point-in-time numbers presented as durable. |
| Notebook won't execute cleanly (missing wheels in 3.14 main env) | Run U3/U4 in a single Python 3.12 report env carrying matplotlib + LightGBM/SHAP + spaCy; heavy visuals are committed images, not re-run at export. |
| Committing artifacts bloats the repo (user flagged "hundreds of artifacts") | Un-gitignore and commit only the curated `report_assets/` images the report embeds, not the full `artifacts_*` sprawl or the embeddings matrix. |

---

## Documentation / Operational Notes

- Env: `~/claude_code_repos/my-uv-envs/avird-2026-eda/` (per `eda/CLAUDE.md`) is Python 3.14 and lacks LightGBM/SHAP/spaCy wheels. Re-rendering those charts requires the sidecars: `avird-2026-eda-target` (Python 3.12, LightGBM/SHAP) and `avird-2026-eda-spacy` (Python 3.12, spaCy + `en_core_web_lg`). Embeddings charts additionally need the gitignored `data/embeddings/` cache (regenerated via `eda/build_narrative_embeddings.py`, which calls the HF Inference Providers API).
- `eda/context/_build_context.py` rebuilds the reference files; the new `findings.md`/`agent_check.md` are hand-authored, not generated — note this in `context/README.md`.

---

## Sources & References

- **Origin document:** `docs/brainstorms/nhtsa-crash-project-requirements.md` (R4, R12, R13, R17)
- Related plans: `docs/plans/2026-05-17-001-feat-narrative-embeddings-unsupervised-plan.md`, `docs/plans/2026-05-20-001-feat-spacy-narrative-eda-plan.md`, `docs/plans/2026-05-22-001-feat-injury-target-analysis-plan.md`
- Related reviews: `docs/reviews/2026-05-25-code-review-injury-target.md`, `docs/code-reviews/2026-05-17-001-embeddings-track-review.md`
- Related learning: `docs/solutions/architecture-patterns/narrative-embeddings-pipeline-2026-05-18.md`
- Design source for agent context: `private/scratch_plans/context_ideas.md`
- Backlog source of truth: `eda/ADS_to_2026_03_16/eda_to_do.md`
