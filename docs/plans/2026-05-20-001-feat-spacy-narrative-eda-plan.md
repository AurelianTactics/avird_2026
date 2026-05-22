---
title: "feat: spaCy narrative EDA on NHTSA AV crash data"
type: feat
status: active
date: 2026-05-20
---

# feat: spaCy narrative EDA on NHTSA AV crash data

## Summary

Build a learning-oriented spaCy EDA layer over the deduped SGO crash narratives. New `eda/eda_utils_spacy.py` wraps spaCy's core capabilities (tokenization, POS/lemma, NER, noun chunks, Matcher/PhraseMatcher, displaCy, similarity); a new notebook `eda/ADS_to_2026_03_16/05_eda_spacy_2026.ipynb` loads the utils against `treated_df['Narrative']` and writes CSV / HTML / PNG artifacts to a per-section artifacts directory.

---

## Problem Frame

The repo already has classical NLP EDA (n-grams, TF-IDF, wordcloud, LDA/NMF topic modeling) on the SGO Narrative field, but no linguistic-features layer: no POS tags, no lemmatization, no named entity extraction, no rule-based phrase matching, no dependency-aware sentence segmentation. The user wants to learn what spaCy actually offers by exercising its main capabilities on real, non-trivial AV crash narrative text, producing inspectable artifacts (CSVs, plots, displaCy HTML) rather than throwaway notebook cells. The bar is "future-me can re-read this and remember what spaCy gave us on this data."

---

## Requirements

- R1. New `eda/eda_utils_spacy.py` exposes reusable functions for the spaCy capabilities the plan covers (load model, tokenize/POS/lemma, NER, noun chunks, sentence segmentation, Matcher, PhraseMatcher, displaCy render, token similarity).
- R2. New `eda/ADS_to_2026_03_16/05_eda_spacy_2026.ipynb` loads the utils via `sys.path.append('..')` + `autoreload`, runs them on `treated_df['Narrative']` produced by the existing dedupe + treatment pipeline, and writes artifacts to a per-section subfolder.
- R3. A new sidecar uv env `~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/` is created on Python 3.12, copying the existing `avird-2026-eda` env's `requirements.txt` and adding `spacy` + the pinned `en_core_web_lg` model wheel. The original 3.14 env is left untouched.
- R4. Each utils function is independently callable (takes a pandas Series of narratives, returns DataFrame / list / dict the notebook can save), matching the existing `eda_utils_*.py` style.
- R5. Each notebook section produces at least one persisted artifact (CSV, PNG, or HTML) under `eda/ADS_to_2026_03_16/artifacts_spacy/<section>/` so results survive a kernel restart.
- R6. Capabilities exercised in this pass: tokenization, POS tagging, lemmatization, named entity recognition, noun chunks, sentence segmentation, rule-based Matcher (token patterns), PhraseMatcher (curated AV-domain seed terms), displaCy rendering, and token similarity against seed words.
- R7. spaCy processing on the ~2.3k deduped narratives runs end-to-end on CPU; the notebook caches the parsed `Doc` objects (via `nlp.pipe` + a serialized DocBin) so re-runs don't reprocess the corpus.
- R8. Stopwords / noise tokens are filtered consistently with the existing repo behavior (e.g., excluding the `[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION]` sentinel, the `XXX` redaction marker, and common AV-corpus stopwords like `av`, `vehicle`, `driver`, `incident`).

---

## Scope Boundaries

- BERTopic / KeyBERT / sentence-transformer embeddings (separate track).
- LLM-based extraction, RAG over narratives, fault attribution (phases P3–P4).
- Training a custom spaCy NER or textcat model — observational EDA only.
- Comparing spaCy NER output against any ground-truth labels (no labels exist).
- Wiring spaCy outputs into the Next.js site or any production surface.
- Refactoring `eda_utils_nlp.py` or `eda_utils_topics.py` to share spaCy tokenization.
- Multi-language support — narratives are English-only.

### Deferred to Follow-Up Work

- Custom NER training on AV-specific entity types (e.g., MANEUVER, CONTACT_AREA): would require labeled data; revisit when a target labeling effort exists.
- Dependency parsing analysis (subject-verb-object extraction for fault patterns): deferred to a follow-up plan focused on fault attribution.
- Re-tokenizing the existing LDA/NMF topic pipelines on spaCy lemmas to compare topic quality: belongs in a topic-modeling iteration plan, not this learning-tour plan.

---

## Context & Research

### Relevant Code and Patterns

- `eda/eda_utils_nlp.py` — sklearn-based n-gram / TF-IDF / wordcloud utils. Establishes the "function takes a pandas Series, returns a DataFrame or matplotlib Axes" contract this plan follows.
- `eda/eda_utils_topics.py` — LDA/NMF pipelines. Establishes the `(topics_df, doc_topic, doc_index)`-style return tuple, the `_clean_series` helper, and the stop-words resolution helper `_build_stopword_set`. The spaCy utils should reuse that stopword convention for parity.
- `eda/eda_utils_dedupe.py` + `eda/eda_utils_treatment.py` + `eda/eda_utils_sgo.py` — upstream pipeline that produces `treated_df` and the `Narrative` series the notebook will consume. Do not modify; load and use.
- `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb` — closest sibling notebook. Use its load/dedupe/treat preamble as the template for `05_eda_spacy_2026.ipynb`.
- `eda/ADS_to_2026_03_16/scrap_eda_topics_examples.py` — pattern for shipping a runnable example file alongside a utils module. Optional analog for spaCy.
- `eda/CLAUDE.md` — "add a function to a new `eda_utils_x.py`" rule, keep it under 1000 lines.

### Institutional Learnings

- The notebook directory uses `sys.path.append('..')` + `%load_ext autoreload` / `%autoreload 2`. Match that exactly so live editing of `eda_utils_spacy.py` works without kernel restarts.
- Narrative redaction sentinels (`[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION]`, `XXX`, `[MAY CONTAIN PERSONALLY IDENTIFIABLE INFORMATION]`) dominate NER false positives if not stripped first. Strip or replace before piping through spaCy.
- The existing topic-modeling pass found Waymo, Cruise, Zoox, Argo, Motional, Transdev, Aurora, GM, Avride dominate as entities. spaCy NER on the raw text will likely pick these up as `ORG`; cross-checking against the `master_entity` column is a natural sanity check.
- `treated_df` has `Narrative - Same Incident ID` (concatenated narratives across duplicate reports). Default the EDA to the single-report `Narrative` column to avoid the concatenation separator polluting sentence segmentation, but offer a switch to use the combined column for parts of the analysis where it adds signal.

### External References

- spaCy 101: https://spacy.io/usage/spacy-101
- Linguistic features (POS, lemma, NER, noun chunks, dependency): https://spacy.io/usage/linguistic-features
- Rule-based matching (Matcher / PhraseMatcher): https://spacy.io/usage/rule-based-matching
- Processing pipelines and DocBin serialization: https://spacy.io/usage/processing-pipelines and https://spacy.io/api/docbin
- `en_core_web_lg` model card: https://spacy.io/models/en#en_core_web_lg

---

## Key Technical Decisions

- **Model choice: `en_core_web_lg`**: User selected this in scoping. 685k word vectors enable meaningful `token.similarity` demos; tradeoff is ~560MB one-time download, accepted.
- **Single utils file, single notebook**: Matches the existing `eda_utils_x.py` per-domain convention. Keeps the learning artifact discoverable in one place.
- **Input series is `treated_df['Narrative']`, not the raw concat**: Avoids the `--- next report ---` separator from `Narrative - Same Incident ID` polluting sentence segmentation. The merged column is exposed as an optional override on the relevant utils.
- **Cache parsed Docs with DocBin**: ~2.3k narratives × `en_core_web_lg` is several minutes of CPU. Cache a serialized DocBin in `artifacts_spacy/_docbin/narratives.spacy` so re-runs are seconds, not minutes. Cache key: hash of narrative series content.
- **Pre-process redaction sentinels before piping to spaCy**: Strip / replace the long `[REDACTED, ...]` markers to a single `<REDACTED>` token so NER doesn't fragment them into spurious entities. This is repo-local cleaning, kept in `eda_utils_spacy.py` rather than refactoring upstream treatment.
- **Artifacts live in `eda/ADS_to_2026_03_16/artifacts_spacy/<section>/`**: Per-section subfolders keep CSV / HTML / PNG outputs grouped and discoverable; one shared root keeps them out of the notebook's working directory.
- **Stopword set extends the existing `_build_stopword_set('english')` with a small AV-corpus add-on (`av`, `vehicle`, `driver`, `incident`, `report`)**: Matches the tip noted in `eda_utils_topics.py`.
- **No spaCy pipeline disabling for speed in v1**: Keep the full pipeline (`tagger`, `parser`, `ner`, `lemmatizer`, `attribute_ruler`) enabled — the EDA wants everything. Re-evaluate only if runtime is unacceptable.

---

## Open Questions

### Resolved During Planning

- Which model: `en_core_web_lg` (user selected).
- Coverage: broad tour across spaCy's core capabilities (user selected).
- Artifact shape: utils file + notebook (user selected).
- Input column: `Narrative` (single-report) by default; `Narrative - Same Incident ID` available as an override.

### Deferred to Implementation

- Exact thresholds for Matcher patterns (e.g., should `intersection` include `t-intersection`, `four-way intersection`): decide while iterating in the notebook.
- Whether to render displaCy NER on every narrative or a sampled subset: decide once notebook runtime is observed.
- Whether to expose a `top_k_similar_tokens` helper across the entire vocabulary or limited to in-corpus tokens: decide based on output usefulness on the first pass.

---

## Implementation Units

- U1. **Create the sidecar Python 3.12 uv env with spaCy + `en_core_web_lg`**

**Goal:** Stand up a parallel `avird-2026-eda-spacy` uv env on Python 3.12 (since spaCy and its compiled dependencies do not ship Python 3.14 wheels as of 2026-05-20). The new env copies the existing env's pinned packages, adds `spacy` and the pinned `en_core_web_lg` model wheel, and leaves the original 3.14 env untouched so other tracks keep working.

**Requirements:** R3

**Dependencies:** None

**Files:**
- Create: `~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/requirements.txt` (copy from `~/claude_code_repos/my-uv-envs/avird-2026-eda/requirements.txt`, then append two lines: a `spacy` pin compatible with numpy 2.x + Python 3.12, and the `en_core_web_lg` wheel URL pinned to a model version compatible with that spaCy)
- Create: `~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/.venv/` (via `uv venv --python 3.12 --prompt avird-2026-eda-spacy`)

**Approach:**
- From the new env directory, create the venv: `uv venv --python 3.12 --prompt avird-2026-eda-spacy`.
- Copy `requirements.txt` from the existing 3.14 env directory verbatim, then append:
    - `spacy>=3.8,<4` (3.8 is the first line that shipped numpy 2.x compatible wheels; lock the floor; verify the latest published version on PyPI before committing the exact pin).
    - `en_core_web_lg @ https://github.com/explosion/spacy-models/releases/download/en_core_web_lg-<X.Y.Z>/en_core_web_lg-<X.Y.Z>-py3-none-any.whl` (substitute `<X.Y.Z>` for the latest model version matching the chosen spaCy minor). This makes the model reproducible via `uv pip install -r requirements.txt` and removes the manual `python -m spacy download` step.
- Activate and install: `source ~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/.venv/Scripts/activate`, then `uv pip install -r requirements.txt`.
- Update `eda/ADS_to_2026_03_16/EDA_README.md` (or add a short note in the new notebook's setup markdown) so the activation command for this notebook points at the new env, not the original.
- If an existing-env pin is incompatible with Python 3.12 (e.g., numpy / pandas pins that only ship 3.13+ wheels), record the relaxation in `requirements.txt` with a comment explaining why — do not silently change the original env.

**Patterns to follow:**
- Existing env layout at `~/claude_code_repos/my-uv-envs/avird-2026-eda/` (requirements.txt at root, `.venv` sibling).
- `EDA_README.md` activation-command convention.

**Test scenarios:**
- Happy path: `uv pip install -r requirements.txt` succeeds inside the activated 3.12 env without source-build fallbacks on `thinc`, `blis`, `murmurhash`, `cymem`, `preshed`.
- Happy path: After install, `python -c "import spacy; nlp = spacy.load('en_core_web_lg'); print(nlp('The Waymo AV stopped at the intersection.').ents)"` prints at least one entity.
- Happy path: `python -c "import numpy, pandas, sklearn, spacy; print(numpy.__version__, pandas.__version__, sklearn.__version__, spacy.__version__)"` — record the resolved set for reproducibility.
- Error path: An existing-env pin refuses to resolve on Python 3.12 — surface the conflict and relax that single pin with an inline comment, do not blanket-downgrade.

**Verification:**
- `spacy.load('en_core_web_lg')` succeeds inside the activated `avird-2026-eda-spacy` env.
- The original `avird-2026-eda` env still activates and imports its existing packages — sidecar did not disturb it.

---

- U2. **Create `eda/eda_utils_spacy.py` skeleton with model loader and narrative preprocessor**

**Goal:** Establish the file, its module docstring, the cached model loader, and the redaction-sentinel preprocessor — the two primitives every later unit depends on.

**Requirements:** R1, R4, R8

**Dependencies:** U1

**Files:**
- Create: `eda/eda_utils_spacy.py`
- Test: covered manually via the notebook in U10; no separate test file (matches existing utils convention — `eda_utils_nlp.py`, `eda_utils_topics.py`, etc. ship without tests).

**Approach:**
- Module docstring explains the four capability groups (linguistic features, NER, rule-based matching, similarity) and the `(takes Series, returns DataFrame)` contract.
- `load_nlp(model_name='en_core_web_lg', disable=())`: returns a cached `spacy.language.Language`. Use `functools.lru_cache` keyed on the args so notebook re-imports are cheap.
- `preprocess_narratives(series, replace_redaction='<REDACTED>', drop_xxx=False)`: strips / replaces the SGO redaction sentinels before piping to spaCy. Returns a new Series aligned to the input index.
- `build_stopwords(extra=('av', 'vehicle', 'driver', 'incident', 'report'))`: returns a set extending sklearn's English stopwords, mirroring `_build_stopword_set` in `eda_utils_topics.py`.

**Patterns to follow:**
- `eda/eda_utils_topics.py`'s `_clean_series` and `_build_stopword_set` helpers.
- `eda/eda_utils_nlp.py`'s module-level docstring style.

**Test scenarios:**
- Happy path: `load_nlp()` returns a `Language` instance; second call returns the same object (lru_cache hit).
- Happy path: `preprocess_narratives(pd.Series(['Vehicle stopped. [REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION].']))` returns a series whose value contains `<REDACTED>` and not the long marker.
- Edge case: `preprocess_narratives` on a series with NaN entries preserves index alignment.
- Edge case: `build_stopwords(extra=None)` returns the base set without crashing.

**Verification:**
- Notebook `import eda_utils_spacy; nlp = eda_utils_spacy.load_nlp()` succeeds and prints model meta.

---

- U3. **Add cached corpus processing via `nlp.pipe` + DocBin**

**Goal:** Provide a one-call helper that parses the entire narrative corpus once, caches it to disk via DocBin, and returns a list of `Doc` objects aligned to a `doc_index`.

**Requirements:** R1, R4, R7

**Dependencies:** U2

**Files:**
- Modify: `eda/eda_utils_spacy.py` (add `parse_corpus` function + DocBin cache helpers)

**Approach:**
- `parse_corpus(series, nlp=None, cache_dir=None, batch_size=64, n_process=1)`: drops NaN, preprocesses via `preprocess_narratives`, hashes the resulting string list, and either loads a matching DocBin from `cache_dir` or runs `nlp.pipe(...)` and writes a fresh one.
- Returns `(docs, doc_index)` matching the `eda_utils_topics.py` convention.
- DocBin filename embeds the content hash so changing the input invalidates the cache automatically.
- `n_process=1` default for Windows compatibility; document that >1 requires `if __name__ == '__main__'` guarding in scripts.

**Patterns to follow:**
- `eda_utils_topics.py`'s `(result, doc_index)` return shape so callers can `pd.Series(..., index=doc_index)` to join back.

**Test scenarios:**
- Happy path: First call parses; second call with same input is materially faster and produces identical entity counts.
- Edge case: Empty series after NaN drop raises a clear `ValueError` (same pattern as `_clean_series`).
- Edge case: `cache_dir=None` skips disk caching and just parses in-memory.
- Integration: `doc_index` round-trips — `pd.Series([d.text[:20] for d in docs], index=doc_index)` aligns with the original.

**Verification:**
- On the ~2.3k-row deduped corpus, first call takes minutes, second call takes seconds, and `len(docs) == len(doc_index)`.

---

- U4. **Linguistic-features utils: tokens, POS, lemmas, sentence segmentation**

**Goal:** Expose the basic-linguistic layer of spaCy as DataFrame-returning functions.

**Requirements:** R1, R4, R6

**Dependencies:** U3

**Files:**
- Modify: `eda/eda_utils_spacy.py`

**Approach:**
- `token_table(docs, doc_index, keep_pos=None, drop_stop=True, drop_punct=True, extra_stop=None)`: returns a long-form DataFrame `[doc_index, token, lemma, pos, tag, is_stop, is_punct]`.
- `top_lemmas_by_pos(docs, doc_index, pos='VERB', top_k=30, extra_stop=None)`: returns a top-K DataFrame of lemmas filtered by POS tag — useful for surfacing the dominant verbs / nouns / adjectives in crash narratives.
- `sentence_stats(docs, doc_index)`: returns a per-document DataFrame `[doc_index, n_sentences, mean_sent_len_tokens, max_sent_len_tokens]`.

**Patterns to follow:**
- `eda_utils_nlp.py`'s `top_ngrams` (returns sorted DataFrame with `count` column).

**Test scenarios:**
- Happy path: `top_lemmas_by_pos(docs, doc_index, pos='VERB', top_k=10)` returns 10 rows, all with `pos == 'VERB'`, sorted descending by count.
- Happy path: `sentence_stats` returns one row per doc, `n_sentences >= 1` for non-empty docs.
- Edge case: `keep_pos=['NOUN']` returns only NOUN tokens.
- Edge case: A doc whose only tokens are punctuation/stopwords yields a `token_table` slice of length 0 but does not raise.
- Integration: `top_lemmas_by_pos(pos='VERB')` includes movement verbs (`stop`, `turn`, `collide`, `travel`) reflecting the actual crash corpus content — basic sanity check.

**Verification:**
- Notebook produces a CSV `artifacts_spacy/linguistic/top_verbs.csv` whose top rows are plausibly crash-related verbs.

---

- U5. **Named Entity Recognition utils + entity-by-entity breakdowns**

**Goal:** Expose NER as DataFrames, and provide a crosstab against `master_entity` for sanity-checking spaCy's `ORG` extraction.

**Requirements:** R1, R4, R6

**Dependencies:** U3

**Files:**
- Modify: `eda/eda_utils_spacy.py`

**Approach:**
- `entity_table(docs, doc_index)`: long-form DataFrame `[doc_index, text, label, start_char, end_char]`.
- `entity_counts_by_label(entity_df, top_k=20)`: returns a per-label top-K table of entity texts.
- `org_vs_master_entity_crosstab(entity_df, treated_df, master_entity_col='master_entity')`: joins `entity_df` (where `label == 'ORG'`) to `treated_df` on `doc_index` and returns a crosstab so the user can see which spaCy-extracted ORGs co-occur with which `master_entity` value (e.g., does spaCy reliably pull "Waymo" out of Waymo reports?).

**Patterns to follow:**
- `eda_utils_basic.py`'s `crosstab_pct` style for the org crosstab.

**Test scenarios:**
- Happy path: `entity_table` on a doc whose text is "Waymo AV stopped at the intersection in Phoenix, Arizona on May 1, 2025." includes at least one of {`ORG`, `GPE`, `DATE`}.
- Happy path: `entity_counts_by_label(label='ORG')` includes the major AV reporters (Waymo, Cruise, Zoox) in its top-20.
- Edge case: A narrative with no entities yields zero rows for that `doc_index` but does not break the join.
- Integration: `org_vs_master_entity_crosstab` aligns on `doc_index` — every row in the crosstab traces back to a real report.
- Error path: Missing `master_entity` column raises a clear `KeyError` (not a cryptic pandas error).

**Verification:**
- Notebook produces `artifacts_spacy/ner/entity_counts_ORG.csv` and a crosstab CSV; manual eyeball confirms spaCy ORGs roughly track `master_entity`.

---

- U6. **Noun-chunk utils**

**Goal:** Surface the noun phrases spaCy extracts — useful for identifying recurrent multi-word concepts (e.g., `parking lot`, `pickup truck`, `left turn`) that the n-gram baseline misses cleanly.

**Requirements:** R1, R4, R6

**Dependencies:** U3

**Files:**
- Modify: `eda/eda_utils_spacy.py`

**Approach:**
- `noun_chunk_table(docs, doc_index, lowercase=True, drop_stop=True)`: long-form DataFrame `[doc_index, chunk_text, root_lemma, root_pos]`.
- `top_noun_chunks(docs, doc_index, top_k=30, lowercase=True, extra_stop=None)`: top-K DataFrame of chunk strings by count.

**Patterns to follow:**
- `eda_utils_nlp.py::top_ngrams` for the top-K convention.

**Test scenarios:**
- Happy path: `top_noun_chunks(top_k=30)` includes plausible AV-domain chunks (e.g., `pickup truck`, `left turn`, `parking lot`).
- Edge case: Chunks consisting only of stopwords are filtered when `drop_stop=True`.
- Edge case: `lowercase=False` preserves the original casing.

**Verification:**
- Notebook produces `artifacts_spacy/linguistic/top_noun_chunks.csv` showing recognizable AV phrases in the top rows.

---

- U7. **Rule-based matching: `Matcher` (token patterns) + `PhraseMatcher` (seed terms)**

**Goal:** Demonstrate spaCy's rule-based layer with two concrete patterns that yield interpretable per-document flags.

**Requirements:** R1, R4, R6

**Dependencies:** U3

**Files:**
- Modify: `eda/eda_utils_spacy.py`

**Approach:**
- `build_av_phrase_matcher(nlp)`: returns a `PhraseMatcher` seeded with a small curated AV-domain list (e.g., `pickup truck`, `parking lot`, `left turn`, `right turn`, `intersection`, `pedestrian`, `bicycle`, `autonomous mode`, `manual mode`, `rear-ended`, `sideswipe`, `merging`).
- `build_maneuver_matcher(nlp)`: returns a `Matcher` with token-pattern examples — e.g., `[{LOWER: "turning"}, {LOWER: "left"}]`, `[{LEMMA: "stop"}, {LOWER: "at"}, {LOWER: "the"}, {LOWER: "intersection"}]`. Three or four patterns is enough to illustrate the API.
- `apply_matcher(docs, doc_index, matcher, label_for=lambda match_id, nlp: ...)`: returns a long-form DataFrame `[doc_index, pattern_label, span_text, start, end]`.
- `match_flags(docs, doc_index, matcher, label_for)`: returns a wide DataFrame indexed on `doc_index` with one boolean column per pattern label — joinable back to `treated_df` for downstream EDA.

**Patterns to follow:**
- Module organization mirrors how `eda_utils_topics.py` groups model builders (`lda_sklearn`, `nmf_sklearn`) at the top of their section.

**Test scenarios:**
- Happy path: A narrative containing "pickup truck" lights up the phrase matcher with one match for that pattern.
- Happy path: A narrative containing "turning left into the parking lot" matches both the `turning left` Matcher pattern and the `parking lot` PhraseMatcher entry.
- Edge case: A narrative with zero matches yields a zero-row slice from `apply_matcher` and an all-False row from `match_flags`.
- Integration: `match_flags` joined to `treated_df` by `doc_index` produces a DataFrame that supports `.groupby('master_entity').sum()` for per-reporter pattern incidence.
- Error path: An empty `Matcher` raises a clear `ValueError` from `apply_matcher` rather than returning an empty DataFrame silently.

**Verification:**
- Notebook produces `artifacts_spacy/matchers/phrase_match_counts.csv` and `match_flags_by_master_entity.csv` — visual scan shows the seed terms have non-trivial coverage.

---

- U8. **displaCy rendering utils (entities + dependency parse)**

**Goal:** Provide a one-call helper that renders displaCy HTML to disk for a sampled subset of narratives — visual inspection complements the tabular artifacts.

**Requirements:** R1, R4, R5, R6

**Dependencies:** U3

**Files:**
- Modify: `eda/eda_utils_spacy.py`

**Approach:**
- `render_displacy_html(docs, doc_index, out_dir, style='ent', sample_n=20, random_state=0)`: writes per-document HTML files (one file per sampled doc) using `spacy.displacy.render(..., page=True)`. Returns the list of paths written.
- Default `style='ent'`; `style='dep'` is also supported but warns on long sentences (dependency renders become unreadable past ~30 tokens).
- Sampling is deterministic given `random_state` so notebook re-runs hit the same sample.

**Patterns to follow:**
- `eda_utils_nlp.py::plot_word_cloud`'s shape (function that takes a series and writes / returns a renderable artifact).

**Test scenarios:**
- Happy path: `render_displacy_html(..., style='ent', sample_n=5)` writes 5 HTML files; opening one in a browser shows highlighted entity spans.
- Edge case: `sample_n` larger than `len(docs)` returns all docs without erroring.
- Edge case: `style='dep'` on a long narrative still produces a (possibly cramped) HTML file rather than crashing.

**Verification:**
- Notebook section produces `artifacts_spacy/displacy/ent/*.html` and (optionally) `artifacts_spacy/displacy/dep/*.html`. Manual open of one HTML confirms entity highlighting.

---

- U9. **Token similarity utils with `en_core_web_lg` vectors**

**Goal:** Demonstrate spaCy's word-vector layer with two concrete EDA outputs: per-seed nearest neighbors, and document-to-document similarity for a small sample.

**Requirements:** R1, R4, R6

**Dependencies:** U3

**Files:**
- Modify: `eda/eda_utils_spacy.py`

**Approach:**
- `most_similar_in_corpus(nlp, seed_words, docs, top_k=15)`: collects the unique non-stop, non-punct lemmas across all `docs`, computes `nlp.vocab[lemma].similarity(nlp.vocab[seed])` for each, and returns a long-form DataFrame `[seed, lemma, similarity]`. Filters lemmas without vectors. Seeds: a small list like `['crash', 'pedestrian', 'turning', 'parking', 'stop']`.
- `doc_similarity_matrix(docs, doc_index, sample_n=50, random_state=0)`: returns a `(sample_n, sample_n)` similarity DataFrame on a deterministic sample — large enough to be interesting, small enough to render as a heatmap.
- Clearly document that "similarity" here is mean-pooled token-vector cosine, not contextual — that's a textbook spaCy-vs-transformer caveat worth surfacing in the artifact.

**Patterns to follow:**
- `eda_utils_topics.py`'s `(result, doc_index)` shape for the doc-level similarity output.

**Test scenarios:**
- Happy path: `most_similar_in_corpus(seed_words=['pedestrian'])` returns lemmas whose top results are intuitively close (e.g., `bicyclist`, `cyclist`, `person`).
- Happy path: `doc_similarity_matrix(sample_n=20)` returns a 20x20 symmetric DataFrame with diagonal == 1.0 (within float tolerance).
- Edge case: A seed word with no vector in `en_core_web_lg` (`nlp.vocab[seed].has_vector == False`) is reported in the return value and does not crash.
- Edge case: `sample_n > len(docs)` clamps to `len(docs)`.

**Verification:**
- Notebook produces `artifacts_spacy/similarity/seed_nearest.csv` and `artifacts_spacy/similarity/doc_similarity_sample.png` (heatmap). Eyeball check on nearest-neighbor results.

---

- U10. **`05_eda_spacy_2026.ipynb`: load data, exercise every util, write artifacts**

**Goal:** Single notebook that demonstrates the full utils surface against real data and produces the artifact tree.

**Requirements:** R2, R5, R6, R7

**Dependencies:** U2, U3, U4, U5, U6, U7, U8, U9

**Files:**
- Create: `eda/ADS_to_2026_03_16/05_eda_spacy_2026.ipynb`
- Create: `eda/ADS_to_2026_03_16/artifacts_spacy/` (directory; populated at runtime — git-ignore policy follows whatever the repo already does for notebook outputs)

**Approach:**
- Section 0 — Setup: `sys.path.append('..')`, `%load_ext autoreload`, `%autoreload 2`, imports including `eda_utils_spacy`. Markdown cell pointing at the sidecar env activation (`~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/.venv/Scripts/activate`) — the model wheel is pinned in `requirements.txt`, so no separate `python -m spacy download` step is needed.
- Section 1 — Load & treat data: copy the load + `dedupe_same_incident` + `apply_all_treatments` preamble from `03_eda_basic_topics_2026.ipynb`. Define `narratives = treated_df['Narrative']`.
- Section 2 — Parse corpus: call `parse_corpus(narratives, cache_dir='artifacts_spacy/_docbin')`. Show length, runtime, and a sample `Doc`.
- Section 3 — Linguistic features (U4): produce `top_verbs.csv`, `top_nouns.csv`, `sentence_stats.csv`, plus a histogram of sentences per narrative.
- Section 4 — NER (U5): produce `entity_table.csv`, `entity_counts_*.csv` for `ORG`, `GPE`, `DATE`, plus the master-entity crosstab.
- Section 5 — Noun chunks (U6): produce `top_noun_chunks.csv`.
- Section 6 — Rule-based matching (U7): produce `phrase_match_counts.csv` and `match_flags_by_master_entity.csv`.
- Section 7 — displaCy (U8): produce `displacy/ent/*.html` (and a small `displacy/dep/*.html` sample).
- Section 8 — Token similarity (U9): produce `seed_nearest.csv` and a similarity heatmap PNG.
- Closing markdown — Notes: brief recap of what spaCy did well / poorly on this corpus (parallel to the `## Notes` cell at the bottom of `03_eda_basic_topics_2026.ipynb`).

**Patterns to follow:**
- `03_eda_basic_topics_2026.ipynb` for cell structure, imports, autoreload, and the load/treat preamble.
- `scrap_eda_topics_examples.py` as a sanity reference for how each utils function is called.

**Test scenarios:**
- Test expectation: none — notebooks are exercised by running them end-to-end. Manual verification is the relevant signal here, matching how the other `0X_eda_*.ipynb` notebooks are validated.

**Verification:**
- Notebook runs top-to-bottom on the activated env without exceptions.
- `artifacts_spacy/` is populated with the expected subfolders (`linguistic/`, `ner/`, `matchers/`, `displacy/`, `similarity/`, `_docbin/`).
- Second run is materially faster than the first (DocBin cache hit).

---

## System-Wide Impact

- **Interaction graph:** Reads from the existing dedupe + treatment pipeline (`eda_utils_dedupe`, `eda_utils_treatment`) — no changes to it. Adds a new file `eda/eda_utils_spacy.py` and one notebook. No existing utils or notebooks are modified.
- **Error propagation:** Failures in spaCy install / model download surface in U1 explicitly; the notebook's setup cell should fail loud (not silent) if `spacy.load` errors so the user knows to run the download command.
- **State lifecycle risks:** The DocBin cache is keyed on a content hash of the input narratives; if the dedupe / treatment pipeline changes upstream, the hash changes and the cache invalidates automatically. No stale-cache footgun.
- **API surface parity:** `eda_utils_spacy.py` matches the existing `eda_utils_*.py` convention (top-level functions, pandas-Series input, DataFrame output, no class hierarchy). No new convention introduced.
- **Integration coverage:** Cross-layer scenario worth surfacing — the `org_vs_master_entity_crosstab` from U5 joins spaCy NER output back to the treated DataFrame. This is the one place a column-name drift in upstream treatment would break the spaCy layer; U5's "Missing `master_entity` column raises a clear `KeyError`" test scenario guards it.
- **Unchanged invariants:** The dedupe pipeline, treatment pipeline, existing topic-modeling utils, and existing notebooks are not modified. The new utils file and notebook are purely additive.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| spaCy has no Python 3.14 wheel as of 2026-05-20. | Resolved by design: U1 creates a sidecar Python 3.12 env (`avird-2026-eda-spacy`) instead of patching the existing 3.14 env. Original env stays untouched. |
| Existing env pin (numpy 2.4.4 / pandas 3.0.2 / sklearn 1.8.0) refuses to resolve on Python 3.12. | U1 documents the resolution: relax the single offending pin inline in the new `requirements.txt` with a comment, do not blanket-downgrade. Verify the resolved set with the `__version__`-printing test scenario before declaring U1 done. |
| `en_core_web_lg` download (~560MB) fails on a flaky connection. | Document the explicit `python -m spacy download en_core_web_lg` command in the notebook's setup markdown. spaCy supports resumable downloads via `pip install` from the wheel URL as a fallback. |
| Parsing ~2.3k narratives with `lg` on CPU is slow first run. | U3's DocBin cache makes re-runs fast. First-run cost is paid once. |
| Redaction sentinels confuse NER and pollute output. | U2's `preprocess_narratives` strips them before piping to spaCy. |
| User expects custom AV entity types (e.g., `MANEUVER`) and is disappointed by stock spaCy NER. | Explicitly listed in "Deferred to Follow-Up Work" — this plan is observational, not a custom-NER training plan. |
| Token similarity output (U9) feels underwhelming because mean-pooled token vectors aren't contextual. | U9's docstring + notebook section call this out explicitly — the EDA value is in seeing the limitation, not in masking it. |

---

## Documentation / Operational Notes

- The notebook itself is the documentation. Each section opens with a markdown cell describing the spaCy capability being exercised and what the resulting artifact shows.
- No CHANGELOG / README updates required — `eda/CLAUDE.md`'s "add a function to a new `eda_utils_x.py`" rule already governs discoverability.
- Update `eda/ADS_to_2026_03_16/eda_to_do.md`'s "NLP EDA To Do" section once the notebook lands, ticking off the spaCy capability tour.

---

## Sources & References

- Repo: `eda/CLAUDE.md`, `eda/ADS_to_2026_03_16/EDA_README.md`, `eda/ADS_to_2026_03_16/eda_to_do.md`
- Related code: `eda/eda_utils_nlp.py`, `eda/eda_utils_topics.py`, `eda/eda_utils_dedupe.py`, `eda/eda_utils_treatment.py`, `eda/eda_utils_sgo.py`
- Related notebook: `eda/ADS_to_2026_03_16/03_eda_basic_topics_2026.ipynb`
- Project context: `docs/brainstorms/nhtsa-crash-project-requirements.md`
- spaCy docs: https://spacy.io/usage/spacy-101, https://spacy.io/usage/linguistic-features, https://spacy.io/usage/rule-based-matching, https://spacy.io/api/docbin, https://spacy.io/models/en#en_core_web_lg
