'''
EDA utils - UMAP projection and Agglomerative clustering over precomputed
embeddings, plus a small matplotlib helper for 2D scatter plots.

Public functions
----------------
* ``umap_project(embeddings, n_components=2, ...)`` -> np.ndarray
* ``agglomerative_cluster(embeddings, n_clusters=None, distance_threshold=None, ...)``
  -> np.ndarray of int labels
* ``plot_umap_2d(coords_2d, labels=None, ...)`` -> matplotlib Axes

UMAP determinism note: UMAP is non-deterministic under ``n_jobs > 1`` even
with ``random_state`` set. ``umap_project`` pins ``n_jobs=1`` for
reproducibility.
'''
import numpy as np


def umap_project(
    embeddings,
    n_components=2,
    n_neighbors=15,
    min_dist=0.1,
    metric='cosine',
    random_state=0,
    n_jobs=1,
):
    '''Project an embedding matrix into ``n_components``-D via UMAP.

    Returns
    -------
    np.ndarray of shape ``(n_rows, n_components)``, dtype ``float32``.
    '''
    _validate_2d(embeddings)
    try:
        import umap
    except ImportError as e:
        raise ImportError(
            'umap_project requires umap-learn (uv pip install umap-learn).'
        ) from e
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
        n_jobs=n_jobs,
    )
    coords = reducer.fit_transform(np.asarray(embeddings))
    return np.asarray(coords, dtype=np.float32)


def agglomerative_cluster(
    embeddings,
    n_clusters=None,
    distance_threshold=None,
    linkage='average',
    metric='cosine',
):
    '''Agglomerative clustering returning an int label array.

    Exactly one of ``n_clusters`` or ``distance_threshold`` must be set.

    Note
    ----
    sklearn requires ``metric='euclidean'`` when ``linkage='ward'``.
    The wrapper surfaces sklearn's error if that combination is used.

    Returns
    -------
    np.ndarray of int labels, length ``n_rows``.
    '''
    _validate_2d(embeddings)
    if (n_clusters is None) == (distance_threshold is None):
        raise ValueError(
            'agglomerative_cluster: pass exactly one of '
            'n_clusters or distance_threshold (got '
            f'n_clusters={n_clusters!r}, distance_threshold={distance_threshold!r}).'
        )

    from sklearn.cluster import AgglomerativeClustering
    model = AgglomerativeClustering(
        n_clusters=n_clusters,
        distance_threshold=distance_threshold,
        linkage=linkage,
        metric=metric,
    )
    labels = model.fit_predict(np.asarray(embeddings))
    return np.asarray(labels, dtype=int)


def plot_umap_2d(
    coords_2d,
    labels=None,
    ax=None,
    figsize=(10, 8),
    title=None,
    alpha=0.6,
    s=10,
    legend=True,
):
    '''2D scatter of UMAP coords, optionally colored by label.

    Returns the matplotlib Axes.
    '''
    import matplotlib.pyplot as plt
    coords = np.asarray(coords_2d)
    if coords.ndim != 2 or coords.shape[1] != 2:
        raise ValueError(
            f'plot_umap_2d expects coords of shape (n, 2), got {coords.shape}'
        )

    if ax is None:
        _, ax = plt.subplots(figsize=figsize)

    if labels is None:
        ax.scatter(coords[:, 0], coords[:, 1], alpha=alpha, s=s)
    else:
        labels_arr = np.asarray(labels)
        for lab in np.unique(labels_arr):
            mask = labels_arr == lab
            ax.scatter(
                coords[mask, 0], coords[mask, 1],
                alpha=alpha, s=s, label=str(lab),
            )
        if legend:
            ax.legend(title='cluster', loc='best', fontsize=8)
    ax.set_xlabel('UMAP-1')
    ax.set_ylabel('UMAP-2')
    if title:
        ax.set_title(title)
    return ax


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _validate_2d(embeddings):
    arr = np.asarray(embeddings)
    if arr.ndim != 2:
        raise ValueError(
            f'embeddings must be 2D, got ndim={arr.ndim} shape={arr.shape}'
        )
