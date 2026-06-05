'''
EDA utils - narrative embeddings via HF Inference Providers + on-disk cache.

Single public function: ``embed_texts(texts, ...)``. Returns:

    embeddings : np.ndarray of shape (n_surviving, dim), dtype float32
    doc_index  : pd.Index aligned with ``embeddings`` row order

Row i of ``embeddings`` corresponds to the source-Series row at
``doc_index[i]``, mirroring the contract of ``eda_utils_topics.py``.

The on-disk cache is content-addressed: each row of the parquet file carries
the sha256 of the stripped text and the embedding vector. Re-runs against the
same ``(model_id, dataset_id, text)`` are free.

Token discovery
---------------
``HF_TOKEN`` is read from the environment. A ``.env`` file at the repo root
is loaded automatically via ``python-dotenv`` when that package is installed.

Example
-------
    from eda_utils_embed import embed_texts
    emb, idx = embed_texts(df['Narrative - Same Incident ID'],
                           dataset_id='narratives_dedup_2026_03_16')
'''
import hashlib
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DEFAULT_MODEL_ID = 'BAAI/bge-base-en-v1.5'
DEFAULT_CACHE_DIR = 'data/embeddings'
DEFAULT_DATASET_ID = 'default'
DEFAULT_BATCH_SIZE = 32
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_BASE = 1.5  # seconds; sleep = backoff_base ** attempt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def embed_texts(
    texts,
    model_id=DEFAULT_MODEL_ID,
    cache_dir=DEFAULT_CACHE_DIR,
    dataset_id=DEFAULT_DATASET_ID,
    batch_size=DEFAULT_BATCH_SIZE,
    max_retries=DEFAULT_MAX_RETRIES,
    backoff_base=DEFAULT_BACKOFF_BASE,
    token=None,
    _client=None,
):
    '''Embed a pandas Series of texts via HF Inference Providers, with cache.

    Parameters
    ----------
    texts : pd.Series or iterable of str
        NaN and whitespace-only rows are dropped; the returned ``doc_index``
        preserves the source index of the surviving rows.
    model_id : str
        HF model id (default ``'BAAI/bge-base-en-v1.5'``).
    cache_dir : str or Path
        Cache directory root. File path is
        ``<cache_dir>/<model_id_slug>/<dataset_id>.parquet``.
    dataset_id : str
        Cache file stem. Group monthly refreshes by stable id.
    batch_size : int
        Loop batch size. One text per HF call inside the batch (the
        multi-string ``feature_extraction`` shape is not in the official
        type signature, so we stay on the safe per-text path).
    max_retries : int
        Per-text retry attempts on transient (HTTP 429 / 5xx) failures.
    backoff_base : float
        Seconds; sleep = ``backoff_base ** attempt``.
    token : str, optional
        HF token. Default: read from ``$HF_TOKEN``.
    _client : object, optional
        Test seam. Inject a stand-in for ``huggingface_hub.InferenceClient``.

    Returns
    -------
    embeddings : np.ndarray  shape ``(n_surviving, dim)`` dtype ``float32``.
    doc_index  : pd.Index    aligned with ``embeddings`` row order.
    '''
    if not isinstance(texts, pd.Series):
        texts = pd.Series(list(texts))
    cleaned = _clean_series(texts)
    if len(cleaned) == 0:
        return np.zeros((0, 0), dtype=np.float32), cleaned.index

    hashes = [_text_hash(t) for t in cleaned]
    cache_file = _cache_path(cache_dir, model_id, dataset_id)
    cache = _load_cache(cache_file)

    missing_unique = {}
    for h, t in zip(hashes, cleaned):
        if h not in cache and h not in missing_unique:
            missing_unique[h] = t

    if missing_unique:
        client = _client if _client is not None else _make_client(model_id, token)
        new_vectors = _embed_missing(
            client, list(missing_unique.items()),
            batch_size, max_retries, backoff_base,
        )
        cache.update(new_vectors)
        _save_cache(cache_file, cache)

    dim = len(next(iter(cache.values())))
    out = np.zeros((len(hashes), dim), dtype=np.float32)
    for i, h in enumerate(hashes):
        out[i] = cache[h]
    return out, cleaned.index


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _normalize_text(text):
    return str(text).strip()


def _text_hash(text):
    return hashlib.sha256(_normalize_text(text).encode('utf-8')).hexdigest()


def _clean_series(series):
    s = series.dropna().astype(str).map(str.strip)
    return s[s.str.len() > 0]


def _model_slug(model_id):
    return model_id.replace('/', '__')


def _cache_path(cache_dir, model_id, dataset_id):
    return Path(cache_dir) / _model_slug(model_id) / f'{dataset_id}.parquet'


def _load_cache(path):
    if not Path(path).exists():
        return {}
    df = pd.read_parquet(path)
    return {
        row['text_hash']: np.asarray(row['vector'], dtype=np.float32)
        for _, row in df.iterrows()
    }


def _save_cache(path, cache):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {'text_hash': h, 'vector': v.tolist(), 'dim': int(v.shape[0])}
        for h, v in cache.items()
    ]
    df = pd.DataFrame(rows)
    tmp = path.with_suffix(path.suffix + '.tmp')
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# HF client + retry
# ---------------------------------------------------------------------------
def _get_token(token):
    if token is not None:
        return token
    tok = os.environ.get('HF_TOKEN')
    if not tok:
        raise RuntimeError(
            "HF_TOKEN env var is not set. Either export HF_TOKEN in your "
            "shell or add it to a .env file at the repo root "
            "(python-dotenv is loaded on import)."
        )
    return tok


def _make_client(model_id, token):
    try:
        from huggingface_hub import InferenceClient
    except ImportError as e:
        raise ImportError(
            "embed_texts requires huggingface_hub "
            "(uv pip install huggingface_hub)."
        ) from e
    return InferenceClient(model=model_id, token=_get_token(token))


def _embed_missing(client, items, batch_size, max_retries, backoff_base):
    '''items: list of (hash, text). Returns dict hash -> np.ndarray.'''
    out = {}
    for i in range(0, len(items), batch_size):
        for h, t in items[i:i + batch_size]:
            out[h] = _embed_one_with_retry(client, t, max_retries, backoff_base)
    return out


def _embed_one_with_retry(client, text, max_retries, backoff_base):
    for attempt in range(max_retries):
        try:
            return _coerce_vector(client.feature_extraction(text))
        except Exception as e:  # noqa: BLE001
            if not _is_transient(e) or attempt == max_retries - 1:
                raise
            sleep_s = backoff_base ** attempt if backoff_base > 0 else 0.0
            if sleep_s > 0:
                time.sleep(sleep_s)


def _coerce_vector(raw):
    '''Normalize HF response shape to a 1D float32 vector.

    bge models return a 1D vector. Some encoders return token-level (2D);
    mean-pool those. Anything higher-rank is an error.
    '''
    arr = np.asarray(raw, dtype=np.float32)
    if arr.ndim == 1:
        return arr
    if arr.ndim == 2:
        return arr.mean(axis=0).astype(np.float32)
    raise ValueError(
        f"feature_extraction returned ndim={arr.ndim} shape={arr.shape}; "
        "expected 1D vector or 2D token-level matrix."
    )


def _is_transient(err):
    status = getattr(getattr(err, 'response', None), 'status_code', None)
    if status is not None:
        return status == 429 or 500 <= status < 600
    name = type(err).__name__
    return name in {
        'ConnectionError', 'Timeout', 'ReadTimeout', 'ConnectTimeout',
    }
