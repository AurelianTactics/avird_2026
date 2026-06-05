'''
EDA utils - nearest-neighbor lookup over precomputed embeddings.

Two functions:

* ``nearest_neighbors(embeddings, ids=None, k=10, metric='cosine')`` ->
  tidy long-form DataFrame with columns
  ``[query_id, rank, neighbor_id, distance]``. Self is excluded from results
  by asking the index for ``k+1`` and dropping the self row.

* ``neighbor_examples(df, neighbors_df, query_ids, text_col, max_chars=400)``
  -> DataFrame for side-by-side narrative display.

Backend is ``sklearn.neighbors.NearestNeighbors`` - fine for the corpus
sizes this project sees (~5k-50k docs). For much larger corpora swap in
FAISS or HNSWlib.
'''
import warnings

import numpy as np
import pandas as pd


def nearest_neighbors(embeddings, ids=None, k=10, metric='cosine'):
    '''K-NN lookup excluding self.

    Parameters
    ----------
    embeddings : np.ndarray  shape (n, dim)
    ids : Sequence, optional
        Row identifiers; default is ``range(n)``.
    k : int
        Neighbors per query (self excluded). Clamped to ``n - 1`` with a
        ``UserWarning`` if the requested ``k`` is too large.
    metric : str
        Distance metric forwarded to ``NearestNeighbors``.

    Returns
    -------
    DataFrame with columns ``query_id``, ``rank`` (1-based),
    ``neighbor_id``, ``distance``.
    '''
    arr = np.asarray(embeddings)
    if arr.ndim != 2:
        raise ValueError(
            f'embeddings must be 2D, got ndim={arr.ndim} shape={arr.shape}'
        )
    n = arr.shape[0]
    if n == 0:
        raise ValueError('embeddings is empty; need at least 2 rows for k-NN.')
    if n < 2:
        raise ValueError(
            f'embeddings has {n} row(s); need at least 2 for nearest neighbors.'
        )
    if ids is None:
        ids = list(range(n))
    else:
        ids = list(ids)
        if len(ids) != n:
            raise ValueError(
                f'ids length {len(ids)} != embeddings rows {n}'
            )

    effective_k = k
    if k > n - 1:
        warnings.warn(
            f'k={k} > n-1={n - 1}; reducing k to {n - 1}.',
            UserWarning,
            stacklevel=2,
        )
        effective_k = n - 1

    from sklearn.neighbors import NearestNeighbors
    nn = NearestNeighbors(n_neighbors=effective_k + 1, metric=metric)
    nn.fit(arr)
    dist, idx = nn.kneighbors(arr, return_distance=True)

    rows = []
    for q_pos in range(n):
        q_id = ids[q_pos]
        rank = 0
        for neighbor_pos, d in zip(idx[q_pos], dist[q_pos]):
            if neighbor_pos == q_pos:
                continue
            rank += 1
            rows.append({
                'query_id': q_id,
                'rank': rank,
                'neighbor_id': ids[neighbor_pos],
                'distance': float(d),
            })
            if rank == effective_k:
                break
    return pd.DataFrame(rows, columns=['query_id', 'rank', 'neighbor_id', 'distance'])


def neighbor_examples(df, neighbors_df, query_ids, text_col,
                      id_col=None, max_chars=400):
    '''Side-by-side query + neighbor narrative table.

    Parameters
    ----------
    df : pd.DataFrame
        Source dataframe carrying the narrative text.
    neighbors_df : pd.DataFrame
        Output of ``nearest_neighbors``.
    query_ids : Sequence
        Subset of ``neighbors_df['query_id']`` values to display.
    text_col : str
        Column in ``df`` holding the narrative text.
    id_col : str, optional
        Column in ``df`` to match against neighbors ids. ``None`` means
        use ``df.index``.
    max_chars : int
        Truncate text to this many characters; truncated rows get an
        ellipsis suffix.

    Returns
    -------
    DataFrame with columns
    ``[query_id, query_text, rank, neighbor_id, distance, neighbor_text]``.
    '''
    if id_col is None:
        lookup = df[[text_col]].copy()
    else:
        lookup = df[[id_col, text_col]].copy().set_index(id_col)
    rows = []
    for q_id in query_ids:
        q_text = _truncate(_lookup_text(lookup, q_id, text_col), max_chars)
        block = neighbors_df[neighbors_df['query_id'] == q_id].sort_values('rank')
        for _, n_row in block.iterrows():
            n_text = _truncate(_lookup_text(lookup, n_row['neighbor_id'], text_col), max_chars)
            rows.append({
                'query_id': q_id,
                'query_text': q_text,
                'rank': int(n_row['rank']),
                'neighbor_id': n_row['neighbor_id'],
                'distance': float(n_row['distance']),
                'neighbor_text': n_text,
            })
    return pd.DataFrame(rows, columns=[
        'query_id', 'query_text', 'rank', 'neighbor_id', 'distance', 'neighbor_text',
    ])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _lookup_text(lookup, key, text_col):
    try:
        val = lookup.loc[key, text_col]
    except KeyError:
        return ''
    if isinstance(val, pd.Series):
        val = val.iloc[0]
    return '' if pd.isna(val) else str(val)


def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + '…'
