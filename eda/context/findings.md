# EDA Findings & Decisions (durable)

Durable structure, decisions, and caveats from the Phase-1 EDA on the SGO ADS
crash dataset (`eda/ADS_to_2026_03_16/`). This file deliberately **excludes
volatile point-in-time statistics** — the data refreshes periodically, so any
specific count/rate/ranking lives in the dated point-in-time report, not here.
Where a number is unavoidable for context it is marked _(point-in-time — see
report)_ and should not be quoted as current fact.

Point-in-time report (numbers, charts, full coverage log):
`eda/ADS_to_2026_03_16/08_eda_report_2026.html` (see `CLAUDE.md` index).

---

## Dataset shape & schema

- **Two source CSVs with different schemas across time.** `data/nhtsa/` holds an
  older file (`…_to_2025_06_16`) and a newer file (`…_2025_06_16_to_2026_03_16`).
  They do **not** share all columns. Never assume a column exists —
  `eda_utils_targets._safe_col` returns an all-NaN series for missing columns;
  mirror that defensive pattern.
- **Old-only columns** include `ADAS/ADS System/Hardware/Software Version`,
  `Mileage`, `Lighting`, `Posted Speed Limit (MPH)`, `Property Damage?`,
  `Roadway Description`, `Notice Received Date`, and the **split** `CP/SV Any Air
  Bags Deployed?` / `CP/SV Was Vehicle Towed?` / `SV Were All Passengers Belted?`.
- **New-only columns** include the **compound** `Any Air Bags Deployed?` and
  `Was Any Vehicle Towed?`, plus `Engagement Status`, `Were All Passengers
  Belted?`, `VIN Decoded`.
- **Old↔new column mappings** (combine/treat with care):
  - `Engagement Status` (new) ≈ `Automation System Engaged?` (old)
  - compound `Any Air Bags Deployed?` (new) vs simple `CP/SV Any Air Bags
    Deployed?` (old)
  - compound `Was Any Vehicle Towed?` (new) vs simple `CP/SV Was Vehicle Towed?`
    (old)
- **Compound vs simple shape.** Newer schema packs both parties into one
  compound string (e.g. `"Yes Subject Vehicle, No Crash Partner"`); older schema
  splits CP/SV into separate Yes/No columns. Binary helpers handle both via
  case-insensitive substring match on `"yes"` (see `eda_utils_targets`).
- **Known data-dictionary caveat:** the SGO data dictionary does not distinguish
  the schema versions; `eda/context/data_dictionary.md/.csv` is a heuristic dump
  of the PDF — spot-check before quoting, and treat version-specific columns by
  presence, not by the dictionary.

## Pipeline decisions (load → dedupe → treat → targets)

- **Load:** `eda_utils_sgo.load_and_concat_csvs(paths)` concatenates the two CSVs
  and prints the schema diff (which columns are old/new-only, dtype mismatches).
- **Dedupe (`eda_utils_dedupe.dedupe_same_incident`):** the feed contains
  multiple reports per physical incident. Grouping: non-blank `Same Incident ID`
  groups by it; blank/null falls back to the composite key (`Reporting Entity`,
  `Incident Date`, `Incident Time (24:00)`, `VIN`); a row missing any fallback
  component is standalone. Per group: sort by (`Report Submission Date`,
  `Report Version`, `Report ID`) **descending**, keep the most recent non-null
  per column, and concatenate all unique narratives latest-first into
  `Narrative - Same Incident ID`.
  - **Caveat:** the narrative join separator `\n\n--- next report ---\n\n`
    **pollutes sentence segmentation** in spaCy / NLP downstream. Strip or
    split on it before linguistic analysis.
- **Treatment (`eda_utils_treatment.apply_all_treatments`):** appends cleaned
  columns alongside the originals (non-destructive). Two themes: (1) light fuzzy
  **categorical consolidation** of near-duplicate strings (Make, Model,
  Operating Entity, Investigating Agency, State or Local Permit, State) —
  strips legal suffixes (inc/llc/corp), trailing punctuation, tab runs; (2)
  **master-entity rollup** collapsing `Operating Entity` + `Reporting Entity`
  into a single canonical `master_entity` (e.g. all Waymo variants → "Waymo").
  Fuzzy consolidation worked well; it emits a suggested mapping a human/LLM can
  review and feed back as an explicit override. Prefer `master_entity` for
  per-entity grouping (raw entity fields have many duplicate IDs / text issues).
- **Treatment ladder (intent):** rules → fuzzy → (future) agentic. Current pass
  is rules + fuzzy only.

## Target construction & analysis caveats

- **Targets kept:** `Injury Reported` and an **SV-speed threshold** target. The
  injury track (notebook `07`) used `SV Speed >= 15`, but `add_all_targets`
  defaults to `sv_speed_threshold=10` and therefore produces an `SV Speed >= 10`
  column — pass the threshold explicitly so the column name matches what you
  expect (`df['SV Speed >= 15']` KeyErrors on the default frame).
  `add_all_targets` builds 7 candidates (`Injury Reported`, `No Injury Reported`,
  `Multi Class Injury`, `Binary Airbag Deployed`, `Binary Vehicle Towed`,
  `SV Speed >= N`, `Potential Non-Trivial Accident`). `Injury Reported` derives
  from `Highest Injury Severity Alleged` and is **strongly imbalanced**
  (~10% positive at the snapshot _(point-in-time — see report; may shift on
  refresh)_). Evaluate with AUC + PR-AUC on a **stratified** holdout; raw
  accuracy is uninformative.
- **Leakage rules (must follow):**
  - Drop the target's source column from features (`Highest Injury Severity
    Alleged` for `Injury Reported`).
  - Drop the **other derived target columns** from the feature set — they
    correlate with each other by construction. Derive the drop set from the
    target-name source-of-truth (`eda_utils_targets` target names), **not** a
    hand-maintained static list. (A static list drifting from the source caused
    a real leak: `SV Speed >= 15` leaked into the `Injury Reported` ranking —
    see `docs/reviews/2026-05-25-code-review-injury-target.md`.)
  - **Co-observed crash-outcome columns** (`Was Any Vehicle Towed?`, `Any Air
    Bags Deployed?`, `SV Precrash Speed (MPH)`, etc.) are post-incident
    co-measurements, not pre-incident signal. Run an explicit pre-incident-only
    contrast pass rather than trusting a combined ranking.
- **Ranking-method caveat:** sorting features by a single mutual-information
  column mixes discrete and continuous MI (not comparable) and inflates
  high-cardinality / datetime columns. Drop/parse datetime columns before
  scoring; don't treat cross-dtype MI as the sole sort key.
- **Filtering decisions:** keep all `Driver / Operator Type`; `Engagement
  Status` has very few not-engaged rows (not worth filtering); within-ODD has
  few non-yes rows — keep them in.
- **Speed needs bucketing.** `SV Precrash Speed (MPH)` is dominated by low/zero
  speeds; analyze in buckets, not raw, and beware tiny high-speed cells.

## Narrative / NLP track facts

- **Redaction pattern:** narrative redaction is concentrated in a handful of
  entities — several now-defunct (Cruise, Argo AI, Motional redact nearly all of
  their rows _(point-in-time — see report)_) plus **Tesla**, the notable redactor
  among *currently-active* entities; high-volume Waymo redacts only a small
  fraction. Two distinct redaction forms exist: (1) a whole-cell sentinel
  `[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION]` (plus `CBI`
  markers), which `eda_utils_sgo.is_redacted` detects; and (2) inline `XXX` spans
  inside an otherwise-readable narrative, which `is_redacted` does **not** match
  — strip those separately. Filter redaction markers plus AV-corpus stopwords
  (`av`, `vehicle`, `driver`, `incident`) consistently in any text analysis.
- **Topic pipelines** (`eda_utils_topics`): four — `lda_sklearn`, `lda_gensim`,
  `nmf_sklearn`, `nmf_gensim` — all return `(topics_df, doc_topic, doc_index)`
  with L1-normalized weights so topics are comparable across pipelines. Join
  back to the frame on `doc_index`.
- **spaCy** (`eda_utils_spacy`): full capability tour (tokenize, POS/lemma, NER,
  noun chunks, sentence segmentation, Matcher + PhraseMatcher, displaCy,
  similarity). Requires the **`avird-2026-eda-spacy` sidecar** (Python 3.12,
  `en_core_web_lg`) — no 3.14 wheel. Parsed `Doc`s cache to a DocBin so re-runs
  don't reprocess.
- **Embeddings** (`eda_utils_embed` + `keybert`/`bertopic`/`neighbors`/
  `emb_cluster`): encoder `BAAI/bge-base-en-v1.5` (768-dim) via HF Inference
  Providers; on-disk parquet cache **content-addressed by sha256 of stripped
  text** at `data/embeddings/<model>/<dataset>.parquet` (gitignored). Re-runs are
  free; a monthly refresh only embeds new incidents. `HF_TOKEN` from `.env`.
  Build with `python eda/build_narrative_embeddings.py` (`--dry-run`, `--limit
  N`). Constraints: KeyBERT MUST use the same model as the embed step (shared
  vector space); BERTopic `.transform()` won't work on new docs
  (`embedding_model=None`). Caveat: the qualitative sections of
  `embeddings_notes.md` (what worked / surprised / useful per method) are
  **unfilled TODOs** — the wiring is documented but the corpus-level findings
  were never written up; do not treat the pipeline as qualitatively validated.

## Environments

- **Main env** `~/claude_code_repos/my-uv-envs/avird-2026-eda/` — Python 3.14.
  Lacks LightGBM / SHAP / spaCy wheels.
- **Target sidecar** `avird-2026-eda-target` — Python 3.12, adds LightGBM + SHAP
  (also matplotlib/sklearn/scipy/pandas). Used for the target-modeling notebook
  and the point-in-time report.
- **spaCy sidecar** `avird-2026-eda-spacy` — Python 3.12, adds spaCy +
  `en_core_web_lg`.
- LightGBM / SHAP / spaCy are **lazy-imported inside functions**, so an agent on
  the main env fails late with a cryptic ImportError — switch to the right
  sidecar first.

## Known code caveats (from reviews)

- **Injury-target utils** (`docs/reviews/2026-05-25-code-review-injury-target.md`):
  committed rankings/SHAP predate the leakage fix (the cross-target leakage
  described under *Target construction & analysis caveats* above) — re-run before
  trusting them; cross-dtype MI sort and qcut single-bin collapse are known
  rough edges.
- **Embeddings utils** (`docs/code-reviews/2026-05-17-001-embeddings-track-review.md`):
  `_embed_one_with_retry(max_retries=0)` returns None; `_is_transient` missed
  `InferenceTimeoutError` (timeout retries were effectively dead); cache is
  persisted only once at the end of a run (an interrupt loses paid-for vectors);
  the cache parquet carries no model/dim fingerprint. Know these before relying
  on a cold embeddings run.

## Deferred (not built this phase)

- `06_eda_clean_up_summary.ipynb` is a data-cleanup/orchestration notebook with
  **open TODOs** — it is not a findings summary and its plumbing is not finished.
- Full backlog (NLP follow-ups, better targets, website surfaces, incremental-
  analysis skill, etc.): the frozen snapshot is in the point-in-time report §5
  (`eda/ADS_to_2026_03_16/08_eda_report_2026.html`); the *living* list, updated on
  future passes, is `eda/ADS_to_2026_03_16/eda_to_do.md`.
