---
title: "feat: Narrative-embeddings unsupervised learning track"
type: feat
status: active
date: 2026-05-17
origin: docs/brainstorms/nhtsa-crash-portfolio-requirements.md
---

# feat: Narrative-embeddings unsupervised learning track

## Summary

Add an embeddings-based unsupervised-learning track for the SGO `Narrative` column. A one-shot Python script computes embeddings via the HF Inference Providers serverless API and writes them to a content-hash on-disk cache; sibling `eda/eda_utils_*.py` modules then read that cache for KeyBERT, BERTopic (HDBSCAN + Agglomerative paths), nearest-neighbors lookup, and UMAP projection + Agglomerative clustering. A focused pytest suite covers the testable logic (cache + batch + retry in the embed adapter, plus pure-logic helpers in neighbors/cluster); a demo notebook in `eda/ADS_to_2026_03_16/` drives the visual exploration and UMAP hyperparameter tuning. Existing `eda_utils_topics.py` (LDA/NMF) is untouched.

---

## Problem Frame

The existing narrative-NLP pipelines in `eda/eda_utils_nlp.py` (n-grams, tf-idf, word cloud) and `eda/eda_utils_topics.py` (LDA + NMF in both sklearn and gensim) cover only bag-of-words methods. The crash narratives are well-suited to embedding-based exploration — semantic neighbors, density-based topic discovery, and dimensionality reduction reveal structure that bag-of-words misses. Embeddings will be computed off-box and cached, not generated on the fly. This plan is the first piece of the `eda-v001-emb` branch (per origin R13 narrative EDA, advancing the path toward R14 narrative-NLP severity classification and producing reusable embeddings the P3 RAG work (R18) can pick up later).

---

## Requirements

- R1. Embeddings for the dedup'd canonical narrative are computed via HF Inference Providers and persisted to disk, keyed so re-runs are idempotent. *(advances origin R13, prepares for origin R14 + R18)*
- R2. A KeyBERT pipeline extracts keywords / keyphrases at corpus level and per-segment, using precomputed embeddings (no on-the-fly encoding). *(advances origin R13)*
- R3. A BERTopic pipeline produces topics from precomputed embeddings, supporting both default HDBSCAN clustering and an Agglomerative substitution via the `hdbscan_model=` slot. *(advances origin R13)*
- R4. A nearest-neighbors helper returns the k closest narratives per query under cosine distance, with a spot-check display helper that shows query + neighbor text side by side. *(advances origin R13)*
- R5. A UMAP projection helper plus an Agglomerative-clustering helper operate on precomputed embeddings and return aligned labels / coords. *(advances origin R13)*
- R6. A single demo notebook in `eda/ADS_to_2026_03_16/` exercises every utility end-to-end on the live dataset and is the validation surface. *(matches existing eda_utils validation pattern)*
- R7. A short markdown writeup committed beside the notebook captures observations, surprises, and AI-tool friction points. *(feeds origin R17 AI-augmented-dev writeup thread)*
- R8. The HF API token is read from environment (`HF_TOKEN`); no secrets are committed.

**Origin requirements advanced:** R13 (baseline EDA narrative analysis), R17 (AI-augmented writeup thread). Prepares ground for R14 (narrative-NLP severity classification) and R18 (P3 RAG embedding choices).

---

## Scope Boundaries

- No second embedding model in this plan — design the cache key so a second one drops in trivially.
- No pytest suite added — validation goes through the demo notebook, matching the existing `eda_utils_*.py` posture.
- No refactor of existing `eda_utils_topics.py` (LDA/NMF) — the new BERTopic util is a sibling, not a replacement.
- No fine-tuning, no domain-adaptation; off-the-shelf encoder only.
- Only the dedup'd canonical narrative is embedded — one embedding per incident, not one per filed report. Tracing each embedding back to its source row is unaffected: every utility returns a `doc_index` aligned with the dedup'd DataFrame, and `Same Incident ID` joins back to the raw rows when needed.
- No site / frontend integration; this is offline EDA only.
- No live HF Endpoints deployment — serverless Inference Providers only.

### Deferred to Follow-Up Work

- **Outlier / novelty detection on embeddings** (cosine-distance-to-centroid, k-NN distance scoring, LOF/IsolationForest on UMAP coords) → next plan in the embeddings track.
- **Multimodal embeddings + tabular metadata** (concatenate embeddings with one-hot / ordinal SGO fields for downstream clustering or weak-supervision targets) → next plan in the embeddings track.
- **Second embedding model for comparison** (e.g. MiniLM vs bge for the same corpus) → can be added later by passing a different `model_id` to the same embed adapter; cache key already separates by model.
- **Pytest test suite for `eda_utils_*.py`** → already on `eda/ADS_to_2026_03_16/eda_to_do.md` backlog; tracked there.

---

## Context & Research

### Relevant Code and Patterns

- `eda/eda_utils_dedupe.py` — `dedupe_same_incident()` produces `Narrative - Same Incident ID` (the input column for embeddings).
- `eda/eda_utils_topics.py` — established return shape `(topics_df, doc_topic, doc_index)` where `doc_index` is the pandas Index of surviving rows so callers can re-align with the source DataFrame. The new BERTopic util should mirror this so notebook code stays uniform.
- `eda/eda_utils_nlp.py` — module shape and docstring style to follow.
- `eda/eda_utils_sgo.py::load_and_concat_csvs` — entry point for loading the two SGO CSVs.
- `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb` — existing minimal demo notebook to mirror in shape for the new demo notebook.
- `eda/ADS_to_2026_03_16/02_eda_utils_validate_2026.ipynb` — existing notebook-as-validation pattern.
- `eda/CLAUDE.md` — "add a function to a new `eda_utils_x.py`" convention is explicit.
- `eda/context/_build_context.py` + `eda/context/README.md` — pattern for build-and-cache artifacts under repo control.

### Institutional Learnings

- No `docs/solutions/` directory exists yet; no prior learnings to reference.
- `eda/ADS_to_2026_03_16/eda_to_do.md` carries the explicit backlog item "make embeddings and project into lower space" — this plan addresses that backlog row.

### External References

- HF Inference Providers feature-extraction docs — `huggingface_hub.InferenceClient.feature_extraction()` accepts `str` officially; `List[str]` works at runtime against the `hf-inference` provider but is not in the type signature, so the adapter should batch internally rather than rely on the multi-string form.
- BERTopic — `hdbscan_model=` parameter accepts any sklearn-compatible cluster model despite the name; `AgglomerativeClustering(n_clusters=N)` substitutes cleanly. `.fit_transform(docs, embeddings=...)` accepts a precomputed matrix and skips the internal encoder.
- KeyBERT — `extract_keywords(docs, doc_embeddings=..., word_embeddings=...)` skips on-the-fly encoding; the constraint is that the vectorizer args passed to `extract_embeddings()` and `extract_keywords()` must match.
- `BAAI/bge-base-en-v1.5` — 768-dim, 512-token context, modern default; outperforms `all-MiniLM-L6-v2` on MTEB and is the standard "good default" for English semantic work.

---

## Key Technical Decisions

- **Single embedding source of truth.** All five downstream methods (KeyBERT, BERTopic, KNN, UMAP, Agglomerative) consume the same precomputed embedding matrix. Rationale: cost control (HF API calls are one-time), reproducibility, and the natural way to wire KeyBERT/BERTopic's precomputed-embedding seams.
- **Content-hash cache key.** The cache file path is `data/embeddings/<model_id_slug>/<dataset_id>.parquet`; inside the file each row carries a SHA-256 of the normalized narrative text and the embedding vector. Rationale: re-runs on the same input are free; adding a second model in the future is additive; appending new monthly data only embeds the new rows.
- **`huggingface_hub.InferenceClient` over raw HTTP.** Use the official SDK with retry/backoff wrapping. Rationale: less brittle than hand-rolled HTTP, auth handling is uniform, easy provider switch later.
- **Internal batching.** The adapter batches text → API in groups of N (default 32), one text per call inside the batch to stay on the documented signature, in a tight loop with simple retry. Rationale: the multi-string `feature_extraction` shape isn't formally supported even though it usually works; we want a stable adapter, not a clever one.
- **One module per method.** Five sibling files (`eda_utils_embed.py`, `eda_utils_keybert.py`, `eda_utils_bertopic.py`, `eda_utils_neighbors.py`, `eda_utils_emb_cluster.py`). Rationale: explicit `eda/CLAUDE.md` convention; each file stays well under the 1000-line trigger.
- **BERTopic both ways in one module.** `bertopic_fit(...)` exposes a `clustering='hdbscan'|'agglomerative'` switch and substitutes the appropriate cluster model via the `hdbscan_model=` slot. Rationale: the agglomerative learning lands inside BERTopic too, not only as a standalone util; lets the demo notebook compare the two on the same corpus side by side.
- **Return-shape parity with `eda_utils_topics.py`.** BERTopic util returns a `topics_df` row-per-topic frame plus `doc_topic` (here, the assigned topic id per doc) and `doc_index`. Rationale: notebook code can call either pipeline with the same downstream wiring.
- **Two validation surfaces: pytest for logic, notebook for exploration.** Pytest covers the logic-heavy or easily-buggy code paths (cache hit/miss/partial in the embed adapter, self-exclusion in KNN, dispatch validation in BERTopic, both-or-neither argument checks in clustering). The demo notebook covers visual / semantic validation (do the keyphrases make sense, do the UMAP clusters look coherent, do neighbor narratives feel related). Rationale: pytest catches the bugs a spot-check misses; the notebook catches the "looks wrong to a human" failures pytest can't.
- **Embedding refresh is a script, not a notebook cell.** `eda/build_narrative_embeddings.py` is a one-shot, idempotent Python script that builds the cache. Rationale: matches the existing `eda/context/_build_context.py` pattern (script writes artifact, notebook reads it); makes monthly refreshes a one-command re-run; keeps the notebook focused on exploration rather than infrastructure.
- **UMAP hyperparameter tuning happens in the notebook, never in the script.** A small grid (or `ipywidgets.interact` slider over `n_neighbors` / `min_dist`) drives visual iteration. Rationale: UMAP tuning is purely visual; a script's write-rerun-look loop is painful for this step.
- **Parquet over npz for cache.** Parquet via pandas/pyarrow because the cache holds (text-hash, vector, metadata) rows; npz forces a parallel index file. Rationale: one self-describing artifact, easy to inspect, plays nicely with future appends.

---

## Open Questions

### Resolved During Planning

- **Embedding service**: HF Inference Providers serverless (`huggingface_hub.InferenceClient` → `hf-inference` provider) — resolved per user answer.
- **Model count**: one solid default (`BAAI/bge-base-en-v1.5`) — resolved per user answer.
- **Stretch scope**: outlier detection + embeddings+metadata deferred to follow-up plan — resolved per user answer.
- **Narrative input**: dedup'd canonical narrative (`Narrative - Same Incident ID`) only — resolved per user answer.
- **Batching shape**: adapter loops one text per call inside batches of 32 — resolved during research (multi-string `feature_extraction` is not officially typed).
- **BERTopic clustering substitution**: `hdbscan_model=AgglomerativeClustering(...)` confirmed via BERTopic docs/issues — resolved during research.
- **KeyBERT precomputed-embedding API**: `extract_keywords(doc_embeddings=, word_embeddings=)` with matching vectorizer args — resolved during research.

### Deferred to Implementation

- Exact retry policy values (backoff base, max attempts, jittered sleep ceiling) — pick during U1 once a few real HF responses are seen.
- Final UMAP hyperparameters (`n_neighbors`, `min_dist`, `n_components` for visualization vs. clustering inputs) — defer to the demo notebook, pick from a small grid during U7.
- KeyBERT keyphrase ngram range and MMR diversity values — defer to the demo notebook tuning loop in U7.
- BERTopic min topic size and HDBSCAN/Agglomerative cluster-count target — defer to U4/U7 once corpus size after dedupe is known empirically.
- Exact dataset-id slug for the cache path (e.g., `narratives_dedup_2026_03_16` vs. a date-range derived id) — pick during U2 once the dedup'd row count is observed.
- HF rate-limit headroom — if serverless throttles, fall back to per-call sleep; only escalate to a paid provider if throttling makes the embed run impractical.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
   STEP 1: cache build (one-shot script, re-run on data refresh)

   +-------------------------------------------------------------+
   |  python eda/build_narrative_embeddings.py [--dry-run]       |
   |  -> load CSVs -> dedupe_same_incident                       |
   |  -> embed_texts(BAAI/bge-base-en-v1.5)                      |
   |  -> data/embeddings/<model>/<dataset_id>.parquet (gitignor) |
   +-------------------------------------------------------------+
                                |
                                v
   STEP 2: exploration notebook reads the cache; never builds it

                 +------------------------------+
                 | dedup'd canonical narratives |
                 |   (Narrative - Same Inc ID)  |
                 |   + cached embedding matrix  |
                 +--------------+---------------+
                                |
                  +-------------+-------------+-------------+--------------+
                  |             |             |             |              |
                  v             v             v             v              v
       +-----------+   +-------------+  +-----------+  +-----------+  +-----------+
       |  KeyBERT  |   |  BERTopic   |  |   KNN     |  |   UMAP    |  | Aggl.     |
       | keywords  |   | (HDBSCAN OR |  | neighbors |  | projection|  | cluster   |
       | keyphrase |   |  Agglomera- |  | per doc   |  |  (2D/5D)  |  |  labels   |
       |           |   |   tive)     |  |           |  | tuned in  |  |           |
       |           |   |             |  |           |  | notebook  |  |           |
       +-----------+   +-------------+  +-----------+  +-----------+  +-----------+
                                |             |             |             |
                                +-------------+-------------+-------------+
                                              |
                                              v
                          +--------------------------------+
                          | 04_eda_narrative_embeddings_   |
                          | 2026.ipynb (visual exploration)|
                          +--------------------------------+
                                              |
                                              v
                          eda/ADS_to_2026_03_16/embeddings_notes.md

   STEP 3 (always available): pytest eda/tests/ -- synthetic /
   mocked tests over the logic in every util above. No API calls.
```

Every downstream util takes the embedding matrix as an argument; none of them call out to the HF API directly. That's the seam that makes the precomputed-embedding story honest end-to-end — and it's also what makes the pytest suite cheap: every test can construct a synthetic matrix and run without any external service.

---

## Implementation Units

- U1. **HF Inference Providers embedding adapter with on-disk cache**

**Goal:** Provide `embed_texts(texts, model_id, cache_dir=...) -> (np.ndarray, pd.Index)` plus a small `embeddings_cache` API that loads/saves the parquet cache and skips already-embedded rows.

**Requirements:** R1, R8

**Dependencies:** None.

**Files:**
- Create: `eda/eda_utils_embed.py`
- Create: `eda/tests/__init__.py` (empty package marker)
- Create: `eda/tests/conftest.py` (shared fixtures: tiny synthetic embedding matrix, mock HF client, tmp cache dir)
- Create: `eda/tests/test_eda_utils_embed.py`

**Approach:**
- Single public function: `embed_texts(texts: pd.Series, model_id='BAAI/bge-base-en-v1.5', cache_dir='data/embeddings', dataset_id=None, batch_size=32) -> (np.ndarray, pd.Index)`.
- Cache file: `<cache_dir>/<model_id_slug>/<dataset_id>.parquet` with columns `text_hash` (sha256 of stripped text), `dim` (int), and per-dim vector columns or a single `vector` array column — pick the parquet-native shape during implementation.
- Normalize input: drop NaN/whitespace, strip; hash the stripped form. Return embeddings aligned with the surviving pandas Index, mirroring `eda_utils_topics.py` return convention.
- Cache flow: on call, hash all incoming texts, look up which hashes are already in the cache file, embed only the missing rows, append to the cache, then build the return matrix in caller-input order.
- HF client: `from huggingface_hub import InferenceClient; client = InferenceClient(model=model_id, token=os.environ['HF_TOKEN'])`. Per-text call inside batches of `batch_size`, with retry-on-transient (HTTP 429/5xx) using a small backoff loop.
- **Token loading:** call `dotenv.load_dotenv()` once at module import (no-op if `python-dotenv` isn't installed — wrap the import in try/except so pytest doesn't depend on it). This means a `.env` at repo root containing `HF_TOKEN=hf_...` is picked up by the script and notebook automatically; users who prefer to export in their shell still work. Tests monkeypatch `os.environ['HF_TOKEN']` directly and don't touch `.env`.
- Module-level constants for default model id, default cache dir, default batch size; no global state otherwise.

**Patterns to follow:**
- Module docstring + helper docstring style from `eda/eda_utils_dedupe.py`.
- Index-preserving return contract from `eda/eda_utils_topics.py`.

**Test scenarios:**
- Happy path: embedding a small pd.Series of 5 sample narratives returns a `(5, 768)` ndarray and an Index of length 5; values are finite.
- Edge case: input with mixed NaN + whitespace + valid text drops NaN/whitespace rows and the returned Index matches the surviving rows only.
- Edge case: re-running the same call against an already-populated cache makes zero HF API requests (assert via a call counter or a request-mock) and returns identical vectors.
- Edge case: cache file does not exist → directory is created and a new parquet is written.
- Edge case: cache hit for some hashes + cache miss for others → only the missing hashes hit the API; final matrix order matches caller input.
- Error path: missing `HF_TOKEN` env var raises a clear `RuntimeError` with a one-line install/setup hint, not a deep `huggingface_hub` traceback.
- Error path: simulated HTTP 429 retries with backoff up to the configured max-attempts, then surfaces the exception.
- Integration: a call with `dataset_id='smoke'` writes a parquet, a second process can load it and round-trip identical vectors.

**Verification:**
- Notebook cell shows the cache file exists at the expected path after first call and second call completes ~instantly with `0` API requests reported.
- Embedding dim matches the published dim of `bge-base-en-v1.5` (768).
- `data/embeddings/` is added to `.gitignore` (do not commit embedding artifacts).

---

- U2. **Embedding refresh script (`eda/build_narrative_embeddings.py`)**

**Goal:** A standalone, idempotent Python script that loads the SGO CSVs, dedupes, embeds, and writes the cache. Re-runs after a monthly data refresh re-embed only new incidents.

**Requirements:** R1

**Dependencies:** U1.

**Files:**
- Create: `eda/build_narrative_embeddings.py`
- Modify: `.gitignore` (add `data/embeddings/`)
- Create (artifact): `data/embeddings/BAAI__bge-base-en-v1.5/<dataset_id>.parquet` (ignored by git)

**Approach:**
- CLI shape: `python eda/build_narrative_embeddings.py [--model-id ...] [--dataset-id ...] [--cache-dir ...] [--batch-size 32] [--dry-run]`. Default model id `BAAI/bge-base-en-v1.5`; default cache dir `data/embeddings`; default `dataset_id` derived from the input CSV filenames (e.g. `narratives_dedup_to_2026_03_16`) so monthly refreshes get a stable id.
- Steps inside the script:
  1. Resolve repo root via `pathlib.Path(__file__).resolve().parents[1]`.
  2. Load both SGO CSVs via `eda_utils_sgo.load_and_concat_csvs`.
  3. Dedupe via `eda_utils_dedupe.dedupe_same_incident`.
  4. Select `Narrative - Same Incident ID` as the input Series.
  5. Call `eda_utils_embed.embed_texts(...)`; print a one-screen receipt (input row count, cache file path, rows added vs. cache-hit, total cache rows after, file size on disk, elapsed seconds, API calls made).
  6. `--dry-run` skips the API call and just reports what would happen.
- Module-level `main()` with `argparse`; no top-level side effects at import time (so the script is also importable from a notebook or test if needed).
- Pattern: mirrors `eda/context/_build_context.py` (script-builds-artifact; notebook reads it).

**Patterns to follow:**
- Script entry shape from `eda/context/_build_context.py`.
- Loader/dedupe wiring from `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb`.

**Test scenarios:**
- Happy path: running with `--dry-run` against the live CSVs prints the expected row count and exits 0 without touching the cache.
- Happy path: first non-dry run writes a cache file at the expected path; second run reports 0 API calls and same cache row count.
- Edge case: invalid `--cache-dir` (file at path instead of dir) raises a clear error before any API call.
- Integration: covered by U7 notebook Section 2 reading the cache produced here.

**Verification:**
- Cache parquet exists at the expected path after first run; second run is fast and reports zero API calls.
- `git status` does not show the cache file (verifies `.gitignore` change).
- `python eda/build_narrative_embeddings.py --help` prints usable help text.

---

- U3. **KeyBERT keyword / keyphrase extraction with precomputed embeddings**

**Goal:** Provide a thin KeyBERT wrapper that consumes the precomputed embedding matrix instead of re-encoding.

**Requirements:** R2

**Dependencies:** U1.

**Files:**
- Create: `eda/eda_utils_keybert.py`
- Create: `eda/tests/test_eda_utils_keybert.py` (light validation tests only — see Test scenarios)

**Approach:**
- Public functions:
  - `keybert_per_doc(texts, doc_embeddings, model_id='BAAI/bge-base-en-v1.5', top_k=10, keyphrase_ngram_range=(1, 3), stop_words='english', use_mmr=True, diversity=0.5)` → DataFrame with one row per doc and a `keyphrases` list column.
  - `keybert_corpus(texts, doc_embeddings, ...)` → DataFrame of the top-N corpus-level keyphrases (aggregated from per-doc scores or a single pass over the joined corpus).
- Under the hood: instantiate `KeyBERT(model=<sentence-transformers/local-model-name-string>)` only for its vectorizer/MMR plumbing; use `kw_model.extract_embeddings(...)` to compute candidate `word_embeddings` once, then `kw_model.extract_keywords(texts, doc_embeddings=doc_embeddings, word_embeddings=word_embeddings, ...)`.
- Honor the documented constraint: same `keyphrase_ngram_range`, `stop_words`, `vectorizer` args between `extract_embeddings` and `extract_keywords`.
- Note in the docstring that `doc_embeddings` shape must match `len(texts)` row order; raise a clear error otherwise.

**Patterns to follow:**
- Module docstring style and "Series in / DataFrame out" shape from `eda/eda_utils_nlp.py`.

**Test scenarios:**
- *pytest, light* — Edge case: passing `doc_embeddings` whose row count doesn't match `len(texts)` raises a `ValueError` with a clear message (test invokes only the validation wrapper, does not call KeyBERT itself).
- *pytest, light* — Happy path: a thin smoke test with a stub `kw_model` (monkeypatched or `unittest.mock`) confirms the function passes `doc_embeddings` and `word_embeddings` through verbatim and that the vectorizer args passed to `extract_embeddings` and `extract_keywords` are identical (the documented KeyBERT invariant).
- *notebook* — Happy path: per-doc call on a 20-doc sample returns a 20-row DataFrame whose `keyphrases` column entries are lists of `(phrase, score)` tuples sorted descending by score.
- *notebook* — Happy path: corpus call returns a top-20 DataFrame with `phrase` and `score` columns, both non-empty.
- *notebook* — Edge case: input with one-word-only narratives (rare but real) returns either an empty keyphrase list for that doc or unigram phrases — never crashes.
- *notebook* — Integration: same input + same params produces deterministic output across two runs (modulo any KeyBERT-internal randomness, which should be off by default for MMR with fixed seed).

**Verification:**
- Notebook cell prints top-30 corpus keyphrases and sanity-checks that domain terms ("intersection," "pedestrian," "rear-ended," "automated") appear.

---

- U4. **BERTopic topic modeling with HDBSCAN and Agglomerative paths**

**Goal:** Provide a BERTopic wrapper that consumes precomputed embeddings and supports a clustering switch.

**Requirements:** R3

**Dependencies:** U1.

**Files:**
- Create: `eda/eda_utils_bertopic.py`
- Create: `eda/tests/test_eda_utils_bertopic.py` (dispatch + validation tests; no real BERTopic fit in pytest)

**Approach:**
- Public function: `bertopic_fit(texts, embeddings, clustering='hdbscan', n_topics=None, min_topic_size=10, umap_n_components=5, umap_n_neighbors=15, random_state=0, **kwargs) -> (topic_model, topics_df, doc_topic, doc_index)`.
- When `clustering='hdbscan'`: default HDBSCAN config with `min_cluster_size=min_topic_size`.
- When `clustering='agglomerative'`: `AgglomerativeClustering(n_clusters=n_topics)` substituted into the `hdbscan_model=` slot (per BERTopic docs).
- Always set `embedding_model=None` and pass `embeddings=embeddings` to `.fit_transform(texts, embeddings=embeddings)` so no on-the-fly encoding happens. `.transform()` won't work on new docs as a result — document that explicitly.
- `topics_df`: row per topic, columns `topic_id`, `size`, `top_words` (comma-joined), `top_weights` (list of c-TF-IDF weights). Mirrors `eda_utils_topics.py` shape so the demo notebook can swap pipelines.
- Helper `topic_keywords_table(topic_model, top_n=10)` for quick display.

**Patterns to follow:**
- Return contract `(topics_df, doc_topic, doc_index)` exactly as `eda/eda_utils_topics.py`.
- ImportError-with-install-hint pattern from `eda/eda_utils_topics.py::lda_gensim`.

**Test scenarios:**
- *pytest, light* — Edge case: passing `clustering='unknown'` raises a clear `ValueError` whose message lists `'hdbscan'` and `'agglomerative'`.
- *pytest, light* — Edge case: embeddings row count mismatch with `len(texts)` raises a clear `ValueError` before BERTopic is constructed.
- *pytest, light* — Edge case: passing `clustering='agglomerative'` without `n_topics` raises a `ValueError` (Agglomerative needs an explicit cluster count).
- *pytest, light* — Dispatch: with `clustering='agglomerative'`, the `hdbscan_model=` arg passed to BERTopic is an `AgglomerativeClustering` instance with the requested `n_clusters` (asserted via a monkeypatched `BERTopic` constructor; no actual fit).
- *notebook* — Happy path (hdbscan): returns a `topics_df` with `topic_id == -1` present (BERTopic's outlier topic) and at least one positive-id topic on the live corpus.
- *notebook* — Happy path (agglomerative): with `n_topics=8`, returns exactly 8 topics, no `-1` outlier topic.
- *notebook* — Integration: same inputs produce the same `doc_topic` assignments across two runs with fixed `random_state` (BERTopic + UMAP determinism caveats — set `random_state` everywhere supported and document the limit).
- *notebook* — Integration: returned `doc_index` aligns with `texts.index` after NaN handling so callers can join back to the source DataFrame.

**Verification:**
- Notebook cell shows the topics_df, manually inspects 2-3 random topics' top words, and confirms agglomerative-vs-hdbscan produces visibly different but plausibly-themed topic sets on the same corpus.

---

- U5. **Nearest-neighbors helper on the embedding matrix**

**Goal:** For each canonical incident, return the k most semantically similar other incidents, with a small spot-check display helper.

**Requirements:** R4

**Dependencies:** U1.

**Files:**
- Create: `eda/eda_utils_neighbors.py`
- Create: `eda/tests/test_eda_utils_neighbors.py` (pure-logic tests on synthetic matrices — runs in milliseconds)

**Approach:**
- Public functions:
  - `nearest_neighbors(embeddings, ids=None, k=10, metric='cosine') -> pd.DataFrame` with columns `query_id`, `rank`, `neighbor_id`, `distance`. Excludes self from results (always asks for k+1 from the index and drops self).
  - `neighbor_examples(df, neighbors_df, query_ids, text_col, max_chars=400) -> pd.DataFrame` for printing query + neighbor narratives side by side.
- Backend: `sklearn.neighbors.NearestNeighbors(n_neighbors=k+1, metric='cosine')` — fast enough for ~5k docs, no extra deps. Note in the docstring that for much larger corpora the user can swap in FAISS or HNSWlib.

**Patterns to follow:**
- "DataFrame out, tidy long form" shape from `eda/eda_utils_basic.py::group_counts`.

**Test scenarios:**
- *pytest* — Happy path: on a synthetic `(20, 8)` embedding matrix with `k=3`, returns a 60-row DataFrame; every `query_id` appears exactly 3 times; `rank` values are `{1, 2, 3}`; no row has `query_id == neighbor_id`.
- *pytest* — Edge case: synthetic input with two near-identical rows (vectors that differ by 1e-6) ranks each as the other's top-1 neighbor with `distance < 1e-4`.
- *pytest* — Edge case: `k > len(embeddings) - 1` is reduced to `len(embeddings) - 1` and the call emits a `UserWarning` (assert via `pytest.warns`).
- *pytest* — Edge case: passing `ids=None` defaults to a 0..n-1 integer index; passing `ids=['a','b','c',...]` (strings) returns string `query_id` / `neighbor_id`.
- *pytest* — Edge case: empty input (zero-row matrix) raises a clear `ValueError`.
- *pytest* — Edge case: `metric='euclidean'` and `metric='cosine'` both run and return distance columns with type `float64`.
- *pytest* — `neighbor_examples`: query text longer than `max_chars` is truncated with an ellipsis; query text shorter than `max_chars` is unchanged.
- *notebook* — Integration: passing `ids=df['Same Incident ID']` returns neighbor ids drawn from that same column, so the result joins back to the source DataFrame.

**Verification:**
- Notebook cell picks 3 query narratives by hand (one mundane, one injury-bearing, one pedestrian) and prints top-5 neighbors; reviewer can eyeball that neighbors are thematically related, not random.

---

- U6. **UMAP projection + Agglomerative clustering helpers**

**Goal:** Two small wrappers that take the embedding matrix and return (a) a 2D/5D projection and (b) a cluster-label vector.

**Requirements:** R5

**Dependencies:** U1.

**Files:**
- Create: `eda/eda_utils_emb_cluster.py`
- Create: `eda/tests/test_eda_utils_emb_cluster.py` (validation + tiny-input smoke tests; plot helper excluded from pytest)

**Approach:**
- Public functions:
  - `umap_project(embeddings, n_components=2, n_neighbors=15, min_dist=0.1, metric='cosine', random_state=0) -> np.ndarray`.
  - `agglomerative_cluster(embeddings, n_clusters=None, distance_threshold=None, linkage='average', metric='cosine') -> np.ndarray` (returns int label array; exactly one of `n_clusters` / `distance_threshold` must be set).
  - `plot_umap_2d(coords_2d, labels=None, ax=None, figsize=(10, 8), title=None, alpha=0.6, s=10)` — matplotlib scatter, colored by label if given.
- ImportError-with-install-hint pattern for `umap-learn`.
- Note in the docstring that UMAP is non-deterministic across `n_jobs > 1` even with a fixed seed; pass `n_jobs=1` for full determinism.

**Patterns to follow:**
- Plot helper signature/figure conventions from `eda/eda_utils_basic.py::plot_top_values`.

**Test scenarios:**
- *pytest* — Happy path: `umap_project` on a synthetic `(50, 16)` matrix returns `(50, 2)` for `n_components=2` and `(50, 5)` for `n_components=5`; all values finite (`np.isfinite(...).all()`); fixed `random_state` + `n_jobs=1` produces identical output across two runs.
- *pytest* — Happy path: `agglomerative_cluster` on a synthetic `(30, 8)` matrix with `n_clusters=5` returns a length-30 `int` array with exactly 5 unique labels.
- *pytest* — Edge case: both `n_clusters` and `distance_threshold` set raises `ValueError` with both arg names in the message.
- *pytest* — Edge case: neither `n_clusters` nor `distance_threshold` set raises `ValueError`.
- *pytest* — Edge case: passing a 1D vector (instead of 2D matrix) raises a clear `ValueError`.
- *pytest* — Edge case: `linkage='ward'` with `metric='cosine'` raises (Ward requires Euclidean) — confirms the wrapper surfaces sklearn's error or pre-validates.
- *notebook* — Edge case: `plot_umap_2d` with no `labels` produces a single-color scatter; with `labels` produces per-cluster colors and a small legend.
- *notebook* — Hyperparameter tuning: a small `ipywidgets.interact` (or 3×3 grid) over `(n_neighbors, min_dist)` ranges produces a comparison grid for visual selection.
- *notebook* — Integration: `umap_project` then `agglomerative_cluster(coords_5d)` and a 2D plot colored by those labels reveals visually coherent groups on the live corpus.

**Verification:**
- Notebook cell renders the 2D UMAP scatter colored by agglomerative labels; reviewer can see at least one obviously coherent cluster.

---

- U7. **Demo + validation notebook tying every util together**

**Goal:** Single notebook that loads data, builds embeddings once, exercises every utility, and serves as the validation surface.

**Requirements:** R1, R2, R3, R4, R5, R6

**Dependencies:** U1, U2, U3, U4, U5, U6.

**Files:**
- Create: `eda/ADS_to_2026_03_16/04_eda_narrative_embeddings_2026.ipynb`

**Approach:**
- Section 0 — Imports + autoreload + paths (mirror `03_eda_basic_topics_2026.ipynb`).
- Section 1 — Load + dedupe; select `Narrative - Same Incident ID` (the input column).
- Section 2 — **Load the cache produced by U2's script** via `embed_texts(...)` with the same args the script used. If the cache row count matches the input row count, embedding work is a no-op; otherwise it auto-fills the gap and reports how many new rows were embedded. A markdown cell at the top of this section says explicitly: "If this is your first run or you just refreshed monthly data, run `python eda/build_narrative_embeddings.py` from the repo root first."
- Section 3 — KeyBERT corpus top-30 + 5 random per-doc keyphrase examples.
- Section 4 — BERTopic HDBSCAN run: topics_df + 3 example topics shown.
- Section 5 — BERTopic Agglomerative run with `n_topics=12`: topics_df + side-by-side comparison with HDBSCAN.
- Section 6 — Nearest-neighbors spot-check: 3 hand-picked queries + their top-5 neighbors with text truncated.
- Section 7 — **UMAP hyperparameter tuning**: a 3×3 (or `ipywidgets.interact`) grid over `(n_neighbors ∈ {5, 15, 50}, min_dist ∈ {0.0, 0.1, 0.5})` of 2D scatter plots. User eyeballs and picks; chosen values are written into the next cell.
- Section 8 — Final UMAP 2D scatter with the chosen hyperparameters, colored by Agglomerative cluster labels.
- Section 9 — Brief markdown commentary cells noting what's interesting, what's surprising, what's noise.

**Patterns to follow:**
- Notebook structure from `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb`.
- `sys.path.append('..')` + `%load_ext autoreload` pattern from the same notebook.

**Test scenarios:**
- *notebook* — Happy path: every section runs top-to-bottom on the live data without errors.
- *notebook* — Integration: second top-to-bottom run takes noticeably less time than the first (no re-embedding work, since the script already populated the cache).
- *notebook* — Edge case: clearing `data/embeddings/<model>/` and re-running Section 2 fails with a clear message pointing the user at the U2 script command (Section 2 reads the cache; it does not rebuild it).
- *notebook* — UMAP tuning: Section 7's grid renders 9 mini-scatters with axes/titles labeled by their `(n_neighbors, min_dist)` values.

**Verification:**
- Notebook executes end-to-end on the live corpus.
- A reviewer reading top-to-bottom can answer: which method surfaced the most useful signal on this corpus.
- After Section 7, the chosen UMAP hyperparameters are written into a code cell (not just kept in a markdown note) so Section 8 is reproducible.

---

- U8. **Embeddings track writeup**

**Goal:** Short markdown writeup capturing observations and AI-tool friction — feeds R17.

**Requirements:** R7

**Dependencies:** U7.

**Files:**
- Create: `eda/ADS_to_2026_03_16/embeddings_notes.md`

**Approach:**
- 3-6 short sections: setup notes (model + provider + cost), what worked, what surprised, what each method was actually useful for, where AI assistance helped vs. misled, open questions feeding the deferred stretch plan.
- Plain prose; no LaTeX or heavy formatting. Keep under ~400 lines.

**Test scenarios:**
- Test expectation: none -- pure markdown writeup, no behavioral code path.

**Verification:**
- File exists, renders cleanly in GitHub's markdown preview, links to the demo notebook by relative path.

---

- U9. **Dependency manifest update**

**Goal:** Add the new Python dependencies to the shared uv env's requirements file so the next env rebuild picks them up.

**Requirements:** Supports U1-U6.

**Dependencies:** None (can land first or last).

**Files:**
- Modify: `~/claude_code_repos/my-uv-envs/avird-2026-eda/requirements.txt` (outside repo per `eda/context/README.md` and `eda/ADS_to_2026_03_16/EDA_README.md`)

**Approach:**
- Add (with reasonable lower bounds, not pinned to exact patches): `huggingface_hub`, `keybert`, `bertopic`, `umap-learn`, `hdbscan`, `pyarrow` (for parquet cache), `pytest` (for U1/U3/U4/U5/U6 tests), `ipywidgets` (for U7 Section 7 hyperparameter tuning), `python-dotenv` (so the script and notebook load `HF_TOKEN` from `.env` automatically).
- After editing the file, run `uv pip install -r requirements.txt` from the env folder per the documented workflow.
- Note: `sentence-transformers` is a KeyBERT/BERTopic transitive dep; it's fine to let it come in transitively but pinning it cheap-ly avoids future surprise.

**Test scenarios:**
- Test expectation: none -- environment manifest change; verified by U1-U6 imports succeeding and `pytest --collect-only eda/tests/` discovering all test files.

**Verification:**
- `python -c "import huggingface_hub, keybert, bertopic, umap, hdbscan, pyarrow, pytest, ipywidgets, dotenv"` succeeds inside the active venv.
- `pytest --collect-only eda/tests/` from the repo root lists every test file created in U1, U3, U4, U5, U6.

---

## System-Wide Impact

- **Interaction graph:** No callbacks, observers, or middleware. The embed adapter is the only module that touches an external service. Downstream utils are pure functions over numpy arrays.
- **Error propagation:** API errors in U1 surface as `RuntimeError` with provider message; downstream utils never see network errors because they consume the cached matrix.
- **State lifecycle risks:** The on-disk parquet cache is the only mutable state. Risks: partial writes on crash mid-run, accidental commit of the cache, cross-machine cache key drift if text normalization changes silently. Mitigations: write to tmp + atomic rename inside U1, `.gitignore` the cache directory in U2, lock the text-normalization function in U1 and avoid changing it after first publish.
- **API surface parity:** New utility modules deliberately echo the (texts, ...) → (DataFrame, ndarray, Index) shape of `eda_utils_topics.py` and `eda_utils_nlp.py`, so notebooks call them interchangeably.
- **Integration coverage:** Two surfaces. (1) `pytest eda/tests/` covers logic/dispatch/validation in U1, U3, U4, U5, U6 with synthetic inputs and mocks — no API calls, runs in under 30 seconds. (2) The U7 notebook exercises every utility on the same live corpus with the same embedding matrix, covering visual/semantic plausibility that pytest cannot.
- **Unchanged invariants:** `eda_utils_topics.py`, `eda_utils_nlp.py`, `eda_utils_dedupe.py`, `eda_utils_sgo.py`, `eda_utils_basic.py`, `eda_utils_co_impact.py` are all untouched. Existing notebooks `01_*`, `02_*`, `03_*` are untouched.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| HF Inference Providers serverless rate-limit blocks a full corpus embed run | Internal batching + per-call retry/backoff in U1; if blocked, sleep-pad between batches; only escalate to a paid provider if these fail. |
| `huggingface_hub.InferenceClient.feature_extraction` returns an unexpected shape (single vector vs. batched matrix vs. token-level matrix) for a given model | Add a one-time shape assertion in U1: first response must be a 1D vector of the model's published dim; raise a clear error otherwise. Mean-pool token-level outputs only if the chosen model returns them (bge does not). |
| BERTopic + UMAP non-determinism even with `random_state` set | Document the limit in the U4 docstring; pin `n_jobs=1` in UMAP calls; accept that `doc_topic` may vary across runs by a small fraction. |
| Cache parquet bloats over time as new monthly data lands | Cache key is per-text-hash, so old rows survive and new rows append. No retention story needed in this plan; revisit if cache exceeds, say, 200 MB. |
| Embedding cache accidentally committed to the repo | `.gitignore` `data/embeddings/` in U2; reviewer should grep `git status` for the path during PR review. |
| KeyBERT `extract_embeddings` / `extract_keywords` argument-mismatch silently producing nonsense | U3 centralizes vectorizer args in one local helper and feeds both calls from it; add a one-line invariant assertion. |
| `bge-base-en-v1.5` not available on the user's HF Inference Providers tier | If the embed call returns 404 / provider-not-supported, fall back to `sentence-transformers/all-MiniLM-L6-v2` (universally available) with a clear console warning. Document this in U1. |

---

## Documentation / Operational Notes

- The shared uv env lives outside the repo at `~/claude_code_repos/my-uv-envs/avird-2026-eda/`. Dependency additions in U9 happen there, not in the repo.
- `HF_TOKEN` must be set in the user's shell (or `.env` loaded by the notebook) before running U2. Add a one-line setup note to `eda/ADS_to_2026_03_16/embeddings_notes.md` in U8.
- The cache directory `data/embeddings/` is intentionally git-ignored (U2). When sharing results, ship the notebook outputs, not the cache.
- No rollout / monitoring concerns — this is offline EDA.

---

## Operational Runbook

End-to-end workflow once every implementation unit has landed. Paths are repo-relative; the shell is PowerShell on Windows (substitute `source` for the activation step on bash). Steps below assume the current directory is the repo root `C:\Users\james\claude_code_repos\avird-2026-eda-v001-emb`.

### A. First-time setup (run once)

1. **Activate the shared uv env**
   ```powershell
   ..\my-uv-envs\avird-2026-eda\.venv\Scripts\Activate.ps1
   ```
   You should see the `(avird-2026-eda)` prefix on your prompt.

2. **Install / update dependencies** (after U9 landed)
   ```powershell
   cd ..\my-uv-envs\avird-2026-eda
   uv pip install -r requirements.txt
   cd ..\..\claude_code_repos\avird-2026-eda-v001-emb
   ```

3. **Make the HF token available** — two options:
   - **Preferred:** create a `.env` file at the repo root containing one line: `HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxx`. The build script and notebook load it automatically via `python-dotenv` on import (U1 / U2). Confirm `.env` is git-ignored: `Select-String -Path .gitignore -Pattern '^\.env$'` should print a match.
   - **Or** export in your current shell: `$env:HF_TOKEN = "hf_..."`. For persistence across shells, add the same line to your PowerShell `$PROFILE`.

   Verify either way with: `python -c "import os, dotenv; dotenv.load_dotenv(); print('TOKEN OK' if os.environ.get('HF_TOKEN','').startswith('hf_') else 'TOKEN MISSING')"`.

4. **Run the test suite to confirm setup**
   ```powershell
   pytest eda/tests/ -v
   ```
   Expected: all tests pass, runtime well under 30 seconds (no API calls — every test uses synthetic input or mocks).

### B. Build / refresh the embedding cache (run once per data refresh)

5. **Dry-run to verify input shape without spending HF API credit**
   ```powershell
   python eda/build_narrative_embeddings.py --dry-run
   ```
   Expected: prints input row count, expected cache path, exits 0. No API calls; no cache file written.

6. **Real run**
   ```powershell
   python eda/build_narrative_embeddings.py
   ```
   Expected first run: prints `rows added: <N>`, `cache_hit: 0`, total elapsed seconds, file path under `data/embeddings/BAAI__bge-base-en-v1.5/`, file size.
   Expected re-run on the same data: prints `rows added: 0`, `cache_hit: <N>`, total elapsed seconds well under a minute, identical file size.

7. **Verify the cache is git-ignored**
   ```powershell
   git status
   ```
   Expected: `data/embeddings/` does NOT appear in the output. If it does, confirm `.gitignore` was updated in U2 and `data/embeddings/` is listed.

### C. Run the demo / exploration notebook

8. **Launch Jupyter**
   ```powershell
   jupyter lab
   ```
   Or `jupyter notebook` if you prefer the classic UI.

9. **Open the notebook**
   Navigate to `eda/ADS_to_2026_03_16/04_eda_narrative_embeddings_2026.ipynb`.

10. **Run all cells**
    `Kernel → Restart Kernel and Run All Cells`. Expected total runtime: a few minutes (BERTopic + UMAP are the longest steps; embeddings load from cache instantly).

11. **Tune UMAP hyperparameters** (Section 7)
    Eyeball the 3×3 grid. Pick the `(n_neighbors, min_dist)` combination that gives the cleanest visible cluster separation for the corpus at hand.
    Write the chosen values into the code cell at the top of Section 8, then re-run Section 8 only.

12. **Capture notes**
    Update `eda/ADS_to_2026_03_16/embeddings_notes.md` with anything surprising you saw (what worked, what surfaced noise, where AI assistance helped or misled). Commit it.

### D. Monthly refresh (when a new SGO CSV lands)

13. **Drop the new CSV under `data/nhtsa/`** (filename pattern `SGO-2021-01_Incident_Reports_ADS_*.csv`).
14. **Update the loader path list** in `eda/build_narrative_embeddings.py` if the script enumerates CSVs by an explicit list rather than a glob — verify during U2.
15. **Re-run step 6** (the build script). Expected: `rows added` equals the count of new dedup'd incidents; existing rows are cache hits.
16. **Re-run step 10** (the notebook). Expected: outputs reflect the larger corpus; UMAP scatter and topic models update.

### E. Troubleshooting

- **`HF_TOKEN` not set** → step 6 raises a clear `RuntimeError`. Confirm `.env` exists at the repo root with the right line, or that you exported in the current shell. The verify command in step 3 isolates whether the token is reachable.
- **HTTP 429 from HF** → step 6 retries with backoff per U1; if it still fails after max attempts, wait 10 minutes (typical free-tier window) and re-run. Cache hits from the partial first run mean step 6 picks up where it stopped.
- **Empty `data/embeddings/` after step 6** → check that the script's working directory was the repo root, not `eda/`; cache path is computed from `Path(__file__).resolve().parents[1] / 'data' / 'embeddings'`.
- **Notebook Section 2 errors with "cache not found"** → step 6 was skipped or pointed at a different `dataset_id`. Re-run step 6 with explicit `--dataset-id` matching the notebook's expected id.
- **`bge-base-en-v1.5` returns 404 from HF Inference Providers** → fall back to `--model-id sentence-transformers/all-MiniLM-L6-v2` (per U1's documented fallback). Notebook continues to work; KeyBERT/BERTopic results will be a touch coarser.

---

## Sources & References

- **Origin document:** [docs/brainstorms/nhtsa-crash-portfolio-requirements.md](../brainstorms/nhtsa-crash-portfolio-requirements.md)
- Related code: `eda/eda_utils_topics.py`, `eda/eda_utils_nlp.py`, `eda/eda_utils_dedupe.py`, `eda/eda_utils_sgo.py`, `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb`
- Existing backlog: `eda/ADS_to_2026_03_16/eda_to_do.md` ("NLP EDA To Do" section — "make embeddings and project into lower space")
- External docs:
  - HF Inference Providers feature-extraction: <https://huggingface.co/docs/inference-providers/en/tasks/feature-extraction>
  - `huggingface_hub.InferenceClient`: <https://huggingface.co/docs/huggingface_hub/package_reference/inference_client>
  - BERTopic clustering options: <https://maartengr.github.io/BERTopic/getting_started/clustering/clustering.html>
  - KeyBERT API: <https://maartengr.github.io/KeyBERT/api/keybert.html>
  - `BAAI/bge-base-en-v1.5` model card: <https://huggingface.co/BAAI/bge-base-en-v1.5>
