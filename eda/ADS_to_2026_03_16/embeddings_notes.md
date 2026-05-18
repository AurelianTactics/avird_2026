# Embeddings track - notes

Companion to [`04_eda_narrative_embeddings_2026.ipynb`](04_eda_narrative_embeddings_2026.ipynb). Keep these notes brief and in plain prose; the goal is institutional memory, not a polished report.

## Setup

- Encoder: `BAAI/bge-base-en-v1.5` (768-dim, modern English semantic default).
- Provider: HF Inference Providers serverless via `huggingface_hub.InferenceClient`. Adapter batches text into groups of 32 and makes one per-text call inside each batch.
- Cache: on-disk parquet at `data/embeddings/BAAI__bge-base-en-v1.5/<dataset_id>.parquet`. Content-addressed by sha256 of the stripped text - re-runs against the same input are free, and monthly refreshes only embed new incidents.
- Token: `HF_TOKEN` loaded from a `.env` file at the repo root (or the shell env) via `python-dotenv`.
- Build script: `python eda/build_narrative_embeddings.py` (use `--dry-run` to inspect counts; `--limit N` to spend only a handful of API calls during smoke validation).

Cost so far: TODO - record after the first full run.

## Validation surfaces

Two independent surfaces, both alive:

1. **`pytest eda/tests/`** - covers logic in the embed adapter (cache hit/miss/partial, normalization, retry/backoff, missing token), plus pure-logic helpers in neighbors and clustering and dispatch checks in BERTopic / KeyBERT via stubs. All tests use synthetic inputs or mocks; no API calls.
2. **`04_eda_narrative_embeddings_2026.ipynb`** - visual / semantic plausibility on the live corpus. Pytest can prove the wiring is correct; only the notebook can answer "does this look right to a human."

## What worked

TODO after running the notebook:

- KeyBERT corpus top-N -
- BERTopic-HDBSCAN -
- BERTopic-Agglomerative -
- Nearest-neighbors -
- UMAP -

## What surprised

TODO. Capture things that didn't match your prior expectations - cluster shapes, neighbor matches, dominant keyphrases.

## What each method was actually useful for

TODO. One-liner per method describing what it does well on this corpus, and what it does poorly:

- **KeyBERT** -
- **BERTopic (HDBSCAN)** -
- **BERTopic (Agglomerative)** -
- **Nearest neighbors** -
- **UMAP** -

## AI-tool friction

TODO. Where AI assistance helped vs. misled during this work. Specific examples beat generalities. Examples to look for:

- Cases where the AI suggested a pattern that didn't fit the precomputed-embedding seam.
- Cases where the AI got HF / KeyBERT / BERTopic API details wrong (the precomputed-embeddings paths are subtle).
- Cases where the AI's first instinct was a heavier abstraction than the project needed.
- Cases where it caught something the human reviewer missed.

## Open questions / handoff to follow-up plans

Tracked in the project plan under *Deferred to Follow-Up Work*:

- Outlier / novelty detection on embeddings.
- Multimodal embeddings + tabular metadata for downstream clustering or weak-supervision targets.
- Second embedding model for comparison (cache key already separates by model).

If anything surfaces during the notebook session that should be added to that list, write it here first and then promote it into the next plan.
