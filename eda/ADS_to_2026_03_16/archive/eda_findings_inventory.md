# EDA Findings Inventory (scratch — U1 harvest)

> **Scratch processing artifact**, not a maintained deliverable. Produced once to feed
> U2 (durable agent-context layer) and U3 (point-in-time report notebook). Not updated
> after those two outputs are written. Source plan:
> `docs/plans/2026-05-31-001-feat-eda-phase-closeout-plan.md`.

**Tag legend**
- **Durability:** `DURABLE` (survives a data refresh — schema/decision/caveat) · `VOLATILE` (point-in-time stat/number) · `IDEA` (spark / backlog direction)
- **Routing:** `AGENT` → goes to `eda/context/findings.md` · `REPORT` → goes to the report notebook · `BOTH` · `DEFER` → backlog summary only
- **Show:** `INLINE` (worth rendering in report) · `LINK` (link out to notebook/util/docs)

---

## A. Treatment / cleaning track
Source: `eda_to_do.md` (treatment follow up, "try with an LLM"), `eda_utils_treatment.py`, `eda_utils_co_impact.py`, `eda_summary_of_notes...md`.

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| A1 | Two source CSVs have **different schemas** across time (old `…_to_2025_06_16`, new `…_2025_06_16_to_2026_03_16`). Old-only cols incl. `ADAS/ADS *Version*`, `Mileage`, `Lighting`, `Posted Speed Limit`, `Property Damage?`, separate `CP/SV Any Air Bags Deployed?`, `CP/SV Was Vehicle Towed?`. New-only incl. compound `Any Air Bags Deployed?`, `Was Any Vehicle Towed?`, `Engagement Status`, `Were All Passengers Belted?`, `VIN Decoded`. | DURABLE | BOTH | INLINE (overview) |
| A2 | Old vs new **column mapping pairs**: `Engagement Status` (new) ≈ `Automation System Engaged?` (old); compound `Any Air Bags Deployed?` (new) vs simple `CP/SV Any Air Bags Deployed?` (old); `Was Any Vehicle Towed?` (new) vs `CP/SV Was Vehicle Towed?` (old). Binary target helpers consume both via case-insensitive substring match on "yes". | DURABLE | BOTH | LINK |
| A3 | **Compound vs simple** columns: newer schema packs both parties into one compound string (e.g. "Yes Subject Vehicle, No Crash Partner"); older schema splits CP/SV into separate Yes/No columns. Any feature logic must handle both shapes. | DURABLE | AGENT | LINK |
| A4 | **Master-entity rollup**: collapse `Operating Entity` + `Reporting Entity` into one canonical `master_entity` (e.g. all Waymo variants → "Waymo"). Decision: generally use Operating Entity, treated into an overall entity that can be assigned. `apply_all_treatments` appends cleaned cols alongside originals. | DURABLE | BOTH | LINK |
| A5 | **Fuzzy categorical consolidation** worked well for Make, Model, Operating Entity, Investigating Agency, State or Local Permit, State. Light text canonicalization (strip legal suffixes inc/llc/corp, trailing punct, tab runs). Produces a suggested mapping a human/LLM can review + feed back as explicit override. | DURABLE | BOTH | LINK |
| A6 | Many duplicate entity IDs; lots of text issues in entity fields — motivated the rollup. | DURABLE | AGENT | LINK |
| A7 | Treatment ladder intent: rules → fuzzy → (future) agentic. Current pass is rules + fuzzy. | IDEA | DEFER | — |
| A8 | Columns flagged as needing treatment / consolidation: Make, Model, State or Local Permit, Operating Entity, Investigating Agency, State. | DURABLE | AGENT | LINK |

## B. Duplicate-incident dedupe track
Source: `eda_utils_dedupe.py` docstring, `eda_to_do.md` (incident duplication results), `eda_summary...md`.

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| B1 | **Dedupe rule**: rows with non-blank `Same Incident ID` group by it; blank/null fall back to composite key (`Reporting Entity`, `Incident Date`, `Incident Time (24:00)`, `VIN`); missing any fallback component → treated as standalone. | DURABLE | BOTH | LINK |
| B2 | **Per-group consolidation**: sort by (`Report Submission Date`, `Report Version`, `Report ID`) desc; keep most recent non-null per column; concat all unique narratives latest-first into `Narrative - Same Incident ID` with separator `\n\n--- next report ---\n\n`. | DURABLE | BOTH | LINK |
| B3 | The `--- next report ---` separator **pollutes sentence segmentation** in NLP/spaCy downstream — known caveat. | DURABLE | AGENT | LINK |
| B4 | Dedupe collapses **3120 → 2344** rows; ~0.426 of incidents have 2+ incident IDs (1329/3120). | VOLATILE | REPORT | INLINE |

## C. Initial explore track (01_eda_initial_explore)
Source: `eda_to_do.md` Initial Explore (all DONE), `01_eda_initial_explore_2026.ipynb`, `eda_summary...md`.

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| C1 | ~Half of incidents the SV was **not moving**; large share of moving incidents were at **low speed**. (rerun live on treated df) | VOLATILE | REPORT | INLINE |
| C2 | **Contact-area matching + heatmap** (SV vs CP contact areas). Earlier independent-count version (`contact_area_compare`) was wrong/not matching; `eda_utils_co_impact` adds per-incident SV×CP pairings. Good website candidate (side/rear/front then granular areas). | DURABLE (method) + VOLATILE (counts) | BOTH | INLINE (rerun light) |
| C3 | Incidents-by-month, by-entity, by time-of-day tables/charts. Time-of-day hard to interpret without exposure (miles driven / road usage). | VOLATILE | REPORT | INLINE |
| C4 | Word cloud, city/state simple plots, data-availability summary. | VOLATILE | REPORT | LINK |
| C5 | **Redaction pattern**: many narratives redacted (location + other useful info); redactions are essentially **Tesla only**, and recent/active. `[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION]` + `XXX` markers. | DURABLE | BOTH | INLINE |
| C6 | ADAS/ADS System/HW/SW Version + redaction ownership investigated (who redacts). | DURABLE | AGENT | LINK |

## D. Target track (04_eda_target_exploration, 07_eda_target_injury)
Source: `eda_to_do.md` Target related (DONE), injury-target plan + review, `eda_summary...md`.

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| D1 | **Targets kept**: `Injury Reported` and `SV Speed >= 15`. `add_all_targets` builds 7 candidates (Injury Reported, No Injury Reported, Multi Class Injury, Binary Airbag Deployed, Binary Vehicle Towed, SV Speed >= N, Potential Non-Trivial Accident). | DURABLE | BOTH | LINK |
| D2 | `Injury Reported` is **imbalanced**: 222 positives / 2344 (~9.5%), derived from `Highest Injury Severity Alleged`. Use AUC + PR-AUC on stratified holdout; raw accuracy uninformative. | VOLATILE (rate) + DURABLE (approach) | BOTH | INLINE |
| D3 | **Leakage rules**: drop the target's source col (`Highest Injury Severity Alleged`) and the other 6 derived target cols from features. Co-observed crash-outcome cols (towed, airbags, precrash speed) are post-incident co-measurements — handle with a contrast pass. | DURABLE | AGENT | LINK |
| D4 | **Univariate signal**: clean operating entity — Waymo ≈ avg incident rate, Zoox + Cruise higher, Tesla a bit higher. Intersections highest rate (a bit above street); work zone + traffic circle higher but small n. | VOLATILE | REPORT | INLINE |
| D5 | **SV speed barely matters** for injury — incidents mostly low-speed; pattern looks like fast CP hitting slow/stopped SV. Higher speeds generally higher rate except 70+ (small n; wants bucketing). | VOLATILE (with durable caveat: speed needs bucketing) | REPORT | INLINE |
| D6 | Weather + roadway condition: **little signal**. Crash With: higher rate with non-motorist / motorcycle / cyclist but small samples. CP pre-crash movement + SV turns look interesting. | VOLATILE | REPORT | INLINE |
| D7 | **Model feature importance** (LightGBM+SHAP): passengers-belted, pre-crash movement, crash-with make sense; some after-the-fact factors dominate (co-observed outcomes). | VOLATILE | REPORT | LINK |
| D8 | **Pre-crash movement heatmap** (SV × CP) is an interesting website candidate; dangerous maneuvers (U-turn, causing accident) are a possible future target. | IDEA | DEFER | INLINE (light) |
| D9 | Filtering decisions: keep all `Driver/Operator Type`; `Engagement Status` — very few not-engaged, not worth filtering; within-ODD — few non-yes, keep them in. | DURABLE | AGENT | LINK |

## E. Topics track (03_eda_basic_topics — LDA/NMF)
Source: `eda_to_do.md` NLP EDA, `eda_utils_topics.py`, `eda_summary...md`.

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| E1 | Four topic pipelines built: `lda_sklearn`, `lda_gensim`, `nmf_sklearn`, `nmf_gensim`. All return `(topics_df, doc_topic, doc_index)`; weights L1-normalized for cross-pipeline comparison. | DURABLE | BOTH | LINK |
| E2 | NMF with more n-grams hints at **Waymo phases** (early: parking lots + Arizona; later: more passenger-car). GM/Cruise + Zoox look isolated. High-volume entities surface location + contact partner + what the vehicle was doing ("stopped", "parked"). | VOLATILE | REPORT | INLINE |
| E3 | LDA/NMF could be expanded (K sweeps, coherence plots, more seeds, hyperparam tuning) — backlog. | IDEA | DEFER | — |

## F. spaCy track (05_eda_spacy)
Source: spaCy plan, `eda_utils_spacy.py`, `eda_to_do.md`, `eda_summary...md`. **Artifacts gitignored + not on disk.**

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| F1 | spaCy capability tour built: tokenization, POS/lemma, NER, noun chunks, sentence segmentation, Matcher + PhraseMatcher, displaCy, similarity. Needs `avird-2026-eda-spacy` sidecar (3.12, `en_core_web_lg`); no 3.14 wheel. DocBin cache for re-runs. | DURABLE | BOTH | LINK |
| F2 | **Matcher + PhraseMatcher** produced an interesting maneuver table; `build_maneuver_matcher` is a website candidate. | IDEA | REPORT | LINK |
| F3 | Redaction sentinel + `XXX` + AV stopwords (`av`, `vehicle`, `driver`, `incident`) filtered consistently. | DURABLE | AGENT | LINK |
| F4 | displaCy HTML / NER crosstab-by-org is a possible website surface (uncertain value for non-DS audience). | IDEA | DEFER | LINK |

## G. Embeddings track (04_eda_narrative_embeddings)
Source: embeddings plan + review, `embeddings_notes.md`, `eda_utils_embed/keybert/bertopic/neighbors/emb_cluster.py`. **Cache gitignored + not on disk; notes TODOs unfilled.**

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| G1 | Encoder `BAAI/bge-base-en-v1.5` (768-dim) via HF Inference Providers; on-disk parquet cache content-addressed by sha256 of stripped text (`data/embeddings/<model>/<dataset>.parquet`). Re-runs free; monthly refresh embeds only new incidents. `HF_TOKEN` from `.env`. Build: `python eda/build_narrative_embeddings.py`. | DURABLE | AGENT | LINK |
| G2 | Pipelines: KeyBERT, BERTopic (HDBSCAN + Agglomerative), nearest-neighbors, UMAP + Agglomerative. KeyBERT MUST share the embed model (same vector space). BERTopic `.transform()` won't work on new docs (`embedding_model=None`). | DURABLE | AGENT | LINK |
| G3 | **`embeddings_notes.md` "what worked / surprised / useful" sections are unfilled TODOs** — the notebook's qualitative findings were never written up. Gap to flag, not a finding. Also "BERTopic not thrilling" per backlog. | DURABLE (gap) | REPORT | LINK |
| G4 | Embeddings findings (cluster shapes, neighbor matches, dominant keyphrases) cannot be regenerated in this closeout without HF API calls — **out of scope**; link out to notebook. | DURABLE (constraint) | AGENT | LINK |

## H. Validate track (02_eda_utils_validate)
| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| H1 | Moving/stopped × severity crosstab (rerun candidate on treated df, optionally with target). | VOLATILE | REPORT | INLINE (light) |

## I. Cleanup/orchestration (06_eda_clean_up_summary) — DEFERRED
| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| I1 | `06_eda_clean_up_summary.ipynb` is a data-cleanup/orchestration notebook with **open TODOs** — NOT a findings summary. State documented as deferred (R5), not finished in this phase. | DURABLE | REPORT (deferred section) | LINK |

---

## J. Reviews (docs/reviews, docs/code-reviews)
| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| J1 | **Injury-target review** (`docs/reviews/2026-05-25-code-review-injury-target.md`): Verdict "Ready with fixes." P1 = `SV Speed >= 15` derived target **leaked into `Injury Reported` feature set** (DEFAULT_DROP_COLS listed 5 of 6); fix at source via `TARGET_COL_NAMES`. Other: cross-dtype MI sort inflates high-cardinality/datetime cols; dead-code cluster; qcut single-bin collapse. | DURABLE (caveat: rankings pre-fix may be tainted) | BOTH | LINK |
| J2 | **Embeddings review** (`docs/code-reviews/2026-05-17-001-embeddings-track-review.md`): Verdict "Ready with fixes." P1s in `eda_utils_embed.py`: `max_retries=0` returns None; `_is_transient` misses `InferenceTimeoutError` (retries effectively dead on timeouts); `_load_cache` uses slow iterrows; build script imports private `_cache_path`. P2: cache persisted once at end (Ctrl-C loses all); no model/dim fingerprint in cache; concurrent runs race on tmp. | DURABLE | AGENT | LINK |
| J3 | Both review verdicts: code is usable; fixes are mostly polish + one real leakage issue (J1) affecting trusted rankings. AI-augmented dev signal: reviewers caught subtle dispatch/shape bugs the author missed. | DURABLE | REPORT (AI-helped-vs-misled) | LINK |

## K. Where AI helped vs misled (origin R17)
Synthesized from reviews + embeddings notes + plans.

| # | Finding | Durability | Routing | Show |
|---|---------|-----------|---------|------|
| K1 | AI **helped**: scaffolding reusable `eda_utils_*` with consistent contracts; multi-reviewer pass caught the cross-target leakage (J1) and the dead `InferenceTimeoutError` retry path (J2) — both subtle, both real. | DURABLE | REPORT | — |
| K2 | AI **misled / friction**: got HF/KeyBERT/BERTopic precomputed-embedding API seams wrong; first instinct often a heavier abstraction than needed; static hand-maintained drop-lists drifted from source of truth (caused J1 leakage). | DURABLE | REPORT | — |
| K3 | Contact-area compare code was initially wrong ("seems odd… not matching… yeah this is wrong") — needed human validation before trusting. | DURABLE | REPORT | — |

## L. Backlog / deferred (eda_to_do.md Backlog + Website + Deferred)
All `DEFER`, summarized in report §5, link back to `eda_to_do.md` for raw list.

| # | Cluster | Routing |
|---|---------|---------|
| L1 | NLP follow-ups: narrative ontology (`narrative_ontology.md` — text→NER→agent graph→golden eval), classification, BERTopic alternatives, embedding-model comparison, narrative dedupe via matching. | DEFER |
| L2 | Better targets: seriousness via data+LLM, weird-maneuver target from pre-crash movement, incident tracking for conclusions. | DEFER |
| L3 | Website surfaces: contact-area heatmap w/ filters, pre-crash-movement heatmap, redaction %-by-entity, cleaned-data browser, target-vs-key-columns, time/region/company breakdowns, displaCy/maneuver-matcher demos. | DEFER |
| L4 | Infra/skill: incremental-analysis skill on new data release, MCP queryable findings, test cases for EDA files, re-review EDA code. | DEFER |
| L5 | Data gaps: data dictionary doesn't note schema versions; lat/long/address not present (maybe Waymo data); mileage exposure missing; FOIA for police reports via data-availability. | DEFER (data-dict caveat is DURABLE → AGENT) |
| L6 | Agent context (THIS PHASE U2): PDF→usable format, columns dir, findings dir, CLAUDE.md expansion, read deep-research findings. Closed by U2. | — |

---

## Coverage check (U1 verification)
- **eda_to_do.md DONE tracks** → Initial Explore (C), incident duplication (B), Target related (D), filtering (D9), Explore-more (C/D), try-with-LLM/treatment (A), contact area (C2), topics (E), spaCy (F), embeddings (G). ✅ all represented.
- **docs/plans** → injury-target (D, J1), embeddings (G, J2), spaCy (F). ✅
- **docs/reviews + docs/code-reviews** → injury-target review (J1), embeddings review (J2). ✅
- **Loose notes** → embeddings_notes.md (G3), narrative_ontology.md (L1), eda_summary...md (woven throughout), eda_to_do backlog (L). ✅
- Every row carries a durability tag and a show/link (or routing) tag. ✅
