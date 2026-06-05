---
title: "Narrative embeddings pipeline: content-addressed cache + precomputed-embedding seams"
date: 2026-05-18
category: architecture-patterns
module: eda/embeddings
problem_type: architecture_pattern
component: tooling
severity: medium
applies_when:
  - "Embedding a corpus through a paid / rate-limited serverless API where re-runs must be free"
  - "Plugging the same embeddings into multiple downstream tools (KeyBERT, BERTopic, neighbors, UMAP) without re-encoding"
  - "Writing tests that must not hit the network or require API credentials"
tags: [embeddings, huggingface, parquet-cache, keybert, bertopic, test-seam, eda]
related_components: [testing_framework, development_workflow]
---

# Narrative embeddings pipeline: content-addressed cache + precomputed-embedding seams

## Context

The EDA track in `eda/ADS_to_2026_03_16/` needed semantic embeddings of ~2,344 incident narratives, exposed to several downstream surfaces (KeyBERT corpus / per-doc, BERTopic with HDBSCAN and Agglomerative, k-NN, UMAP). Three forces shaped the design:

- HF Inference Providers is paid per call and serverless. A naive script that re-embeds on every run wastes money and time.
- KeyBERT and BERTopic both *want* to do their own encoding internally, but the project needs them to share a vector space with the embed step so results stay comparable across tools.
- Tests must run without `HF_TOKEN` and without network. A unit test that needs a live API is a unit test nobody runs.

A session-scoped code review (`docs/code-reviews/2026-05-17-001-embeddings-track-review.md`) validated the shape of this pipeline; the open P1/P2 fixes there are bugs *inside* the pattern, not problems with the pattern itself.

## Guidance

Build the embedding pipeline as **one cached `embed_texts` function** plus **thin adapters** that consume its output. The shape:

1. **Content-addressed on-disk cache.** Key each vector by `sha256(text.strip())`. Store as a parquet file at `<cache_dir>/<model_id_slug>/<dataset_id>.parquet`. Re-runs against the same `(model_id, dataset_id, text)` are free; monthly refreshes only pay for *new* rows. See `eda/eda_utils_embed.py:147` (`_cache_path`) and `:151` (`_load_cache`).

2. **Precomputed-embedding seam for downstream tools.** Adapters do *not* re-encode the corpus. Instead:
   - `eda_utils_keybert.py` calls `kw_model.extract_keywords(docs, doc_embeddings=doc_embeddings, word_embeddings=word_embeddings, ...)`. Only the small candidate-phrase vocabulary is encoded locally.
   - `eda_utils_bertopic.py` constructs BERTopic with `embedding_model=None` and passes the precomputed matrix into `.fit()`.
   - `eda_utils_neighbors.py` and `eda_utils_emb_cluster.py` consume the numpy matrix directly.

   The hard invariant: KeyBERT's candidate-phrase encoder *must* be the same model as the one that produced `doc_embeddings`. This is enforced by funnelling `DEFAULT_MODEL_ID = 'BAAI/bge-base-en-v1.5'` from `eda_utils_embed.py` (one source of truth — see review finding P2 #8).

3. **KeyBERT vectorizer-kwargs invariant.** `extract_embeddings(...)` and `extract_keywords(...)` must receive *identical* `keyphrase_ngram_range` / `stop_words` / `min_df`. The adapter builds one `vectorizer_kwargs` dict and forwards it to both calls (`eda/eda_utils_keybert.py:79-93`). Drifting them silently misaligns candidate vectors against the wrong vocabulary.

4. **Test seam via dependency injection.** Each module that touches an external library exposes a leading-underscore client kwarg:
   - `embed_texts(..., _client=None)` injects a `StubInferenceClient`
   - `keybert_per_doc(..., _kw_model=None)` injects a stand-in for `keybert.KeyBERT`
   - BERTopic adapter takes an `_model` injector
   `eda/tests/conftest.py:30` defines `StubInferenceClient` — a deterministic, hash-seeded float32 vector generator that can also fake transient HTTP failures (`fail_first_n`, `status`). Tests run without `HF_TOKEN`, without network, and stay fast.

5. **Optional-dep guarding.** Every import of a heavy / optional dependency (`huggingface_hub`, `keybert`, `bertopic`, `matplotlib`, `umap-learn`) is wrapped in `try/except ImportError` and re-raised with an actionable `uv pip install <pkg>` hint. See `_make_client` at `eda/eda_utils_embed.py:190` and `_make_kw_model` at `eda/eda_utils_keybert.py:159`.

6. **Build script as the operator surface.** `eda/build_narrative_embeddings.py` exposes `--dry-run` (count without paying) and `--limit N` (smoke-test with a handful of API calls) so the cache can be populated safely from the command line, and so an agent can pre-flight before spending tokens.

## Why This Matters

- **Cost discipline.** Without the cache, every notebook re-run or test session would re-bill HF for the same 2,344 narratives. With it, the second run costs $0 and the cache compounds across monthly refreshes.
- **Tool comparability.** When KeyBERT, BERTopic, and k-NN all consume the same `(n_docs, 768)` matrix, their outputs are directly comparable — "the cluster KeyBERT names X is the same cluster BERTopic clusters together." Different encoders per tool would silently break that.
- **Test velocity.** Pytest covers the embed adapter's cache hit/miss/partial paths, normalization, and retry/backoff *without* a token or network — see `eda/tests/test_eda_utils_embed.py`. The notebook then handles the semantic plausibility check on real data. Two surfaces, both alive.
- **Refactor safety.** The DI seams mean the day HF deprecates a method, only `_make_client` changes; tests don't.

## When to Apply

- The corpus is small-to-medium (hundreds to low tens of thousands of texts), where a parquet of cached vectors fits comfortably on disk.
- Embeddings are produced through a paid or rate-limited API and re-runs are expected.
- Two or more downstream tools need to consume the *same* embeddings (otherwise just call the API once and skip the cache layer).
- Tests need to be hermetic.

Skip the pattern when: the corpus is so large that a single parquet won't fit (move to a content-addressed store like SQLite or a vector DB); or when only one tool consumes the embeddings and it has its own perfectly fine internal encoder.

## Examples

**The pipeline as wired in this repo:**

```python
# 1. Embed once. Cache hit on re-run.
from eda_utils_embed import embed_texts

emb, doc_idx = embed_texts(
    df['Narrative - Same Incident ID'],
    dataset_id='narratives_dedup_2026_03_16',
)
# emb: (n, 768) float32 ; doc_idx aligned to surviving rows

# 2. Feed precomputed embeddings into each downstream tool.
from eda_utils_keybert import keybert_corpus, keybert_per_doc
from eda_utils_bertopic import bertopic_fit
from eda_utils_neighbors import nearest_neighbors

top_phrases = keybert_corpus(df['narrative'].tolist(), emb, top_k=30)
topic_model, topics = bertopic_fit(df['narrative'].tolist(), emb)
nn = nearest_neighbors(emb, k=5)
```

**The test seam pattern (deterministic, no token, no network):**

```python
# conftest.py provides StubInferenceClient
def test_round_trip_via_disk(tmp_path, stub_client_factory):
    client = stub_client_factory(dim=8)
    emb, idx = embed_texts(
        pd.Series(['a', 'b', 'c']),
        cache_dir=tmp_path,
        dataset_id='test',
        _client=client,
    )
    # Second call: zero API hits, identical vectors from cache.
    client2 = stub_client_factory(dim=8)
    emb2, _ = embed_texts(
        pd.Series(['a', 'b', 'c']),
        cache_dir=tmp_path,
        dataset_id='test',
        _client=client2,
    )
    assert client2.calls == []
```

**The KeyBERT invariant in code:**

```python
# Build the dict ONCE; forward it to BOTH calls.
vectorizer_kwargs = dict(
    keyphrase_ngram_range=keyphrase_ngram_range,
    stop_words=stop_words,
    min_df=min_df,
)
_, word_embeddings = kw_model.extract_embeddings(docs, **vectorizer_kwargs)
keywords = kw_model.extract_keywords(
    docs,
    doc_embeddings=doc_embeddings,
    word_embeddings=word_embeddings,
    top_n=top_k,
    **vectorizer_kwargs,
)
```

## Related

- `docs/code-reviews/2026-05-17-001-embeddings-track-review.md` — open P1/P2 fixes inside this pattern (transient-error coverage, `max_retries=0` guard, model_id deduplication, cache fingerprint).
- `eda/ADS_to_2026_03_16/embeddings_notes.md` — companion notebook notes; the "what worked / what surprised" sections are TODOs until the notebook is run end-to-end.
- `eda/CLAUDE.md` — convention: new EDA helpers go in `eda_utils_x.py` at the base of `eda/`, split when a file exceeds 1000 LOC.
