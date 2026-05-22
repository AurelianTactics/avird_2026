---
title: "Code review: feat narrative-embeddings unsupervised track"
date: 2026-05-17
plan: docs/plans/2026-05-17-001-feat-narrative-embeddings-unsupervised-plan.md
run_id: 20260517-212225-f24d96b4
status: open
---

# Code review — embeddings track (session-scoped)

## Scope

Session-scoped review of the just-implemented work for the plan
`docs/plans/2026-05-17-001-feat-narrative-embeddings-unsupervised-plan.md`
(units U1-U9). No git base; 12 new files + `.gitignore` tweak.

**Files reviewed:**

- `eda/eda_utils_embed.py`
- `eda/eda_utils_keybert.py`
- `eda/eda_utils_bertopic.py`
- `eda/eda_utils_neighbors.py`
- `eda/eda_utils_emb_cluster.py`
- `eda/build_narrative_embeddings.py`
- `eda/tests/conftest.py` + 5 test files
- `eda/ADS_to_2026_03_16/04_eda_narrative_embeddings_2026.ipynb`
- `eda/ADS_to_2026_03_16/embeddings_notes.md`
- `.gitignore` (2-line addition)

**Reviewer team:** correctness, testing, reliability, adversarial, security, performance, kieran-python, project-standards, agent-native, learnings-researcher. (Maintainability dropped due to a rate-limit during dispatch; kieran-python covered the same lens.)

**Verdict:** Ready with fixes. Five high-value, low-effort fixes are concentrated in `eda/eda_utils_embed.py`. Everything else can land as residual work or stay deferred.

---

## P1 — High (fix before this carries semantic weight)

### 1. `_embed_one_with_retry` returns `None` when `max_retries=0`

**File:** `eda/eda_utils_embed.py:210`
**Reviewers:** kieran-python (P1, conf 95), correctness (P3, conf 100), reliability (P3, conf 85), adversarial (P2) — **4-way cross-reviewer agreement**

`range(max_retries)` with `max_retries=0` runs zero iterations; the function falls off the end and returns `None`. The caller stores that None into the cache dict; `_save_cache` then crashes with `AttributeError: 'NoneType' object has no attribute 'tolist'`. Default is 5, so only callers explicitly passing 0 hit it.

**Fix:**
```python
def _embed_one_with_retry(client, text, max_retries, backoff_base):
    if max_retries < 1:
        raise ValueError(f'max_retries must be >= 1, got {max_retries}')
    ...
```

### 2. `_is_transient` misses `huggingface_hub.InferenceTimeoutError`

**File:** `eda/eda_utils_embed.py:243`
**Reviewer:** reliability (P2, conf 90 — verified in installed `huggingface_hub` source)

`huggingface_hub.inference._client` wraps every httpx `TimeoutError` into `InferenceTimeoutError`. That class has no `.response` attribute, and its `__name__` is `'InferenceTimeoutError'` — not in the name set `{'ConnectionError', 'Timeout', 'ReadTimeout', 'ConnectTimeout'}`. Result: every API timeout escapes all 5 retries immediately. This is the most common transient condition on a serverless API (cold-start, model loading, transient overload), so the retry loop is effectively dead for the case it most needs to cover.

**Fix:** Add an `isinstance(err, TimeoutError)` check (catches `InferenceTimeoutError` plus future subclasses), or add `'InferenceTimeoutError'` to the name set.

### 3. `_load_cache` uses `df.iterrows()`

**File:** `eda/eda_utils_embed.py:151-158`
**Reviewers:** kieran-python (P1, conf 90), performance (low, conf 75)

Iterating row-by-row to rebuild the hash→ndarray dict costs ~1-3s per cold load at 5k rows vs. ~50ms vectorized. One-line fix.

**Fix:**
```python
return dict(zip(
    df['text_hash'],
    df['vector'].map(lambda v: np.asarray(v, dtype=np.float32)),
))
```

### 4. Build script imports private `_cache_path`

**File:** `eda/build_narrative_embeddings.py:100`
**Reviewer:** kieran-python (P1, conf 85)

The `from eda_utils_embed import embed_texts, _cache_path` line pulls a leading-underscore private helper. If `_cache_path` is renamed during an internal refactor, the script breaks silently at runtime.

**Fix:** Promote `_cache_path` to public `cache_path` in `eda_utils_embed.py` and update the import. Or inline the two-line derivation in the build script.

---

## P2 — Moderate

### 5. Cache only persisted once, at end of `_embed_missing`

**File:** `eda/eda_utils_embed.py:117`
**Reviewer:** adversarial (P2)

Ctrl-C or a single non-transient error mid-run discards every previously paid-for vector. For a full 2,344-narrative run that takes ~8 minutes, one network blip = restart from zero.

**Fix:** Persist the cache every N successful API calls (e.g., every batch of 32). Trade-off is more parquet rewrites, but the atomic-write pattern is already in place.

### 6. No fingerprint inside the cache parquet

**File:** `eda/eda_utils_embed.py:151-158`
**Reviewers:** adversarial (P2), security (P3)

Cache is content-addressed by text hash but not by model or vector dim. A poisoned, stale, or different-model parquet at the cache path is loaded blindly — the function trusts whatever bytes it finds.

**Fix:** Add a `model_id` and `dim` column (or a small sidecar `_meta.json`) and validate on load. Reject the cache and rebuild if model_id mismatches the caller.

### 7. Concurrent build-script runs race on `.parquet.tmp`

**File:** `eda/eda_utils_embed.py:104, 117-118, 161-171`
**Reviewers:** adversarial (P2), security (P2)

Two parallel runs against the same `cache_dir` / `model_id` / `dataset_id` both load the same cache, both pay HF for the missing texts, and both write to the same `.parquet.tmp` path. Last writer wins; the other's paid-for embeddings are silently dropped.

**Fix:** Acceptable as a known limitation for a single-user EDA tool. If you want to harden it: include a process id or timestamp in the tmp suffix, or take an advisory lock on the cache file.

### 8. `DEFAULT_MODEL_ID` duplicated in three modules

**Files:** `eda/eda_utils_embed.py:42`, `eda/eda_utils_keybert.py:31`, `eda/build_narrative_embeddings.py:31`
**Reviewer:** kieran-python (P2, conf 80)

All three currently agree on `'BAAI/bge-base-en-v1.5'`. KeyBERT MUST use the same model as the embed step (the candidate-phrase embeddings must share a vector space with the doc embeddings). Three independent string definitions means a future model swap in one file silently breaks the others.

**Fix:**
```python
# eda_utils_keybert.py
from eda_utils_embed import DEFAULT_MODEL_ID

# build_narrative_embeddings.py
from eda_utils_embed import DEFAULT_MODEL_ID
```

### 9. `plot_umap_2d` imports matplotlib bare

**File:** `eda/eda_utils_emb_cluster.py:106`
**Reviewers:** kieran-python (P2), reliability (P3) — cross-reviewer

Every other optional-dep entry point in the module family wraps the import in `try/except ImportError` and raises with an install hint. `plot_umap_2d` does `import matplotlib.pyplot as plt` bare. Missing matplotlib produces a raw `ModuleNotFoundError` instead of an actionable message.

**Fix:**
```python
try:
    import matplotlib.pyplot as plt
except ImportError as e:
    raise ImportError(
        'plot_umap_2d requires matplotlib (uv pip install matplotlib).'
    ) from e
```

### 10. `_coerce_vector` accepts empty / NaN / zero-norm vectors silently

**File:** `eda/eda_utils_embed.py:222-236`
**Reviewers:** reliability (P3), adversarial (P3)

`np.asarray([])` is `ndim=1, shape=(0,)` — passes the 1D check and gets cached as a zero-length vector. Subsequent runs hit cache, `dim = len(next(iter(cache.values()))) == 0`, output is shape `(n, 0)` — silent corruption persisted to disk.

**Fix:** Add `if arr.size == 0: raise ValueError('feature_extraction returned empty vector')` and consider rejecting NaN / Inf / zero-norm responses.

### 11. Path traversal via `--model-id` / `--dataset-id`

**File:** `eda/eda_utils_embed.py:143-148`
**Reviewers:** security (P2), adversarial (P3)

`_model_slug` only replaces `/`. A user passing `--model-id ../../something` (or `\` on Windows, drive prefixes, reserved names CON / PRN / NUL) writes a parquet outside the intended cache dir. Low risk in dev tooling, trivial fix.

**Fix:** Replace the slug helper with a stricter sanitizer: keep alnum / `_` / `-` / `.`, replace everything else with `_`, then strip leading dots. Same treatment for `dataset_id` before path interpolation.

### 12. `rows cache-hit` count can be negative or misleading

**File:** `eda/build_narrative_embeddings.py:154-160`
**Reviewers:** kieran-python (P2), correctness (P3)

The receipt line `cache-hit = n_nonempty - rows_added` assumes 1:1 alignment with the current input's non-empty count. If input has duplicates, or partial overlap with prior cache, the subtraction misleads (and could go negative in edge cases).

**Fix:** Clamp to zero (`max(0, ...)`) and note in the receipt that it's an estimate. Or compute it from intersection of input hashes against the loaded cache directly.

---

## P3 — Low

| # | File | Issue | Reviewer |
|---|------|-------|----------|
| 13 | `eda_utils_embed.py:100` | Empty input returns `(0, 0)` ndarray instead of `(0, dim)`. Downstream consumers keyed off `emb.shape[1]` break. | correctness, adversarial |
| 14 | `eda_utils_embed.py:242` | HTTP 408 not in the transient set. Acceptable in practice (HF rarely emits 408). | correctness |
| 15 | `04_eda_narrative_embeddings_2026.ipynb` §8 | Notebook clusters raw 768-d embeddings; plan U6 design implied clustering on the 5-D UMAP coords. Either intentional or drift. | correctness |
| 16 | `eda_utils_neighbors.py`, `eda_utils_emb_cluster.py` | `k=0`, `k<0`, `n_clusters=0`, negative `n_clusters` not pre-validated; sklearn errors are opaque. | adversarial |
| 17 | `eda_utils_neighbors.py:128-143` | `neighbor_examples` uses nested `iterrows()`. Fine at EDA sizes; less readable than merge. | kieran-python |

---

## Testing gaps

- **No test file for `build_narrative_embeddings.py`.** Plan U2 lists 4 pytest scenarios (`--dry-run`, first/second run cache behavior, invalid `--cache-dir` guard, helpers). All unimplemented. `_derive_dataset_id` regex and `_format_bytes` unit crossings untested. (kieran-python, testing — cross-reviewer)
- `_coerce_vector` 2D mean-pool and `ndim>=3` error paths are unreachable in tests — `StubInferenceClient` always returns 1D. (testing)
- `test_round_trip_via_disk` asserts shape and zero-API-calls but never compares vector **values** across the parquet boundary. A precision-loss bug in `_save_cache`/`_load_cache` would pass. (testing)
- `test_partial_cache_hit_only_embeds_new` doesn't verify that cached `x` / `y` values match the originally computed ones. (testing)
- `_is_transient` name-based branch (`ConnectionError`, `Timeout`) never exercised — all retry tests inject `response.status_code`. (testing)
- `max_retries=0` not tested. (kieran-python, reliability — would catch finding #1)
- `neighbor_examples` `_lookup_text` KeyError and NaN paths untested. (kieran-python, testing)
- `test_umap_project_deterministic_with_fixed_seed` uses `assert_array_equal` (bit-exact). Could be brittle across umap-learn / numba bumps on Windows; `assert_allclose` would be more robust. (testing)

---

## Residual risks (worth knowing, not blocking)

- `_text_hash` strips only leading/trailing whitespace. Internal whitespace variation (newlines, multiple spaces) produces distinct hashes. If upstream normalization ever changes, the same narrative re-embeds under a different key.
- `_save_cache` rewrites the whole parquet on every save. Fine at <100 MB; revisit beyond.
- BERTopic `.transform()` won't work on new docs after `bertopic_fit` because `embedding_model=None`. The module docstring flags this; the function docstring does not.
- UMAP on a degenerate input (all rows identical) can produce NaN. Not pre-validated.
- `_save_cache` never evicts hashes absent from the current run. Preprocessing changes that re-hash the same narratives bloat the cache over time.

---

## Clean lenses (no findings)

- **Project standards (`eda/CLAUDE.MD`):** Zero violations. All five `eda_utils_*.py` files at the base of `eda/`, all <250 LOC. (project-standards)
- **Agent-native parity:** Pass. All errors are typed exceptions; `--dry-run` and `--limit` give agents safe pre-flight surfaces; `HF_TOKEN` never appears in print / log / exception messages. One observation: full-run stdout is human-formatted; an agent parsing rows-added would need fragile string matching. (agent-native)
- **Past learnings (`docs/solutions/`):** Directory doesn't exist yet. This work would seed entries on HF caching, KeyBERT / BERTopic precomputed-embedding seams, and UMAP determinism on Windows. (learnings-researcher)
- **Secret handling:** `HF_TOKEN` correctly handled — env-only, never logged, never in error messages. `.env` and `data/embeddings/` correctly gitignored. (security)

---

## Suggested fix order (if you want to land cleanly)

1. **P1 #1** — `max_retries=0` guard (3 lines in `eda_utils_embed.py`)
2. **P1 #2** — `InferenceTimeoutError` in `_is_transient` (1 line)
3. **P1 #3** — `_load_cache` vectorization (3 lines)
4. **P1 #4** — Promote `_cache_path` → public `cache_path` (rename + update one import in build script)
5. **P2 #8** — Collapse `DEFAULT_MODEL_ID` to one source of truth (delete 2 duplicates, add 2 imports)

Combined: ~30 minutes of work, all surgical, no architectural change. Everything else can stay deferred.

---

## Per-reviewer artifacts

Partial artifacts (most reviewers returned findings inline due to mid-run rate limits; only 3 wrote disk artifacts):

- `/tmp/compound-engineering/ce-code-review/20260517-212225-f24d96b4/agent-native.json`
- `/tmp/compound-engineering/ce-code-review/20260517-212225-f24d96b4/learnings.json`
- `/tmp/compound-engineering/ce-code-review/20260517-212225-f24d96b4/testing.json` (empty — write failed)
