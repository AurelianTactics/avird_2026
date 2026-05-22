'''
EDA utils - BERTopic topic modeling over precomputed embeddings.

Two clustering paths through one entry point:

* ``clustering='hdbscan'``  - default BERTopic config; produces an outlier
  topic ``-1`` and a variable number of positive-id topics.
* ``clustering='agglomerative'`` - substitutes ``AgglomerativeClustering(
  n_clusters=n_topics)`` into BERTopic's ``hdbscan_model=`` slot, yielding
  exactly ``n_topics`` clusters and no outlier topic.

The wrapper always sets ``embedding_model=None`` and feeds the precomputed
matrix via ``BERTopic.fit_transform(docs, embeddings=...)`` so no docs are
re-encoded. ``.transform()`` on new docs will not work afterward; document
that explicitly in calling code.

Return contract mirrors ``eda_utils_topics.py``::

    topic_model : BERTopic instance (post-fit)
    topics_df   : DataFrame, one row per topic
    doc_topic   : np.ndarray of int topic ids, one per surviving doc
    doc_index   : pd.Index aligned with ``doc_topic``
'''
import numpy as np
import pandas as pd


_VALID_CLUSTERING = ('hdbscan', 'agglomerative')


def bertopic_fit(
    texts,
    embeddings,
    clustering='hdbscan',
    n_topics=None,
    min_topic_size=10,
    umap_n_components=5,
    umap_n_neighbors=15,
    random_state=0,
    top_n_words=10,
    _bertopic_cls=None,
    _umap_model=None,
    **bertopic_kwargs,
):
    '''Fit BERTopic on precomputed embeddings.

    Parameters
    ----------
    texts : pd.Series or Sequence[str]
        Document texts. Row order must match ``embeddings``.
    embeddings : np.ndarray  shape (n_docs, dim)
        Precomputed doc embeddings.
    clustering : {'hdbscan', 'agglomerative'}
        Cluster model substituted into BERTopic's ``hdbscan_model=`` slot.
    n_topics : int, optional
        Required when ``clustering='agglomerative'``; ignored for HDBSCAN.
    min_topic_size : int
        HDBSCAN ``min_cluster_size`` and BERTopic ``min_topic_size``.
    umap_n_components, umap_n_neighbors : int
        BERTopic's internal UMAP dimensionality-reduction step.
    random_state : int
        Seed for the UMAP step.
    top_n_words : int
        Words kept per topic in the returned ``topics_df``.
    _bertopic_cls, _umap_model :
        Test seams.
    **bertopic_kwargs :
        Forwarded to ``BERTopic(...)``.

    Returns
    -------
    (topic_model, topics_df, doc_topic, doc_index)
    '''
    if clustering not in _VALID_CLUSTERING:
        raise ValueError(
            f"clustering must be one of {_VALID_CLUSTERING}, "
            f"got {clustering!r}"
        )
    if clustering == 'agglomerative' and n_topics is None:
        raise ValueError(
            "clustering='agglomerative' requires n_topics to be set "
            '(AgglomerativeClustering needs an explicit cluster count).'
        )

    docs, idx = _prepare_texts(texts)
    embeddings = np.asarray(embeddings, dtype=np.float32)
    _validate_alignment(docs, embeddings)

    cluster_model = _build_cluster_model(clustering, n_topics, min_topic_size)
    umap_model = _umap_model if _umap_model is not None else _build_umap_model(
        umap_n_components, umap_n_neighbors, random_state,
    )

    BERTopicCls = _bertopic_cls if _bertopic_cls is not None else _import_bertopic()
    topic_model = BERTopicCls(
        embedding_model=None,
        umap_model=umap_model,
        hdbscan_model=cluster_model,
        min_topic_size=min_topic_size,
        **bertopic_kwargs,
    )
    topics, _probs = topic_model.fit_transform(docs, embeddings=embeddings)
    topics_df = topic_keywords_table(topic_model, top_n=top_n_words)
    doc_topic = np.asarray(topics, dtype=int)
    return topic_model, topics_df, doc_topic, idx


def topic_keywords_table(topic_model, top_n=10):
    '''Tidy per-topic top-words DataFrame.

    Columns
    -------
    topic_id     : int (BERTopic's `-1` outlier topic is included if present)
    size         : int document count
    top_words    : comma-joined str of the top-N words
    top_weights  : list of c-TF-IDF weights aligned with ``top_words``
    '''
    info = topic_model.get_topic_info()
    rows = []
    for _, info_row in info.iterrows():
        topic_id = int(info_row['Topic'])
        size = int(info_row['Count'])
        terms = topic_model.get_topic(topic_id) or []
        terms = list(terms)[:top_n]
        rows.append({
            'topic_id': topic_id,
            'size': size,
            'top_words': ', '.join(w for w, _ in terms),
            'top_weights': [float(s) for _, s in terms],
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _prepare_texts(texts):
    if isinstance(texts, pd.Series):
        return texts.tolist(), texts.index
    docs = list(texts)
    return docs, pd.RangeIndex(len(docs))


def _validate_alignment(docs, embeddings):
    arr = np.asarray(embeddings)
    if arr.ndim != 2:
        raise ValueError(
            f'embeddings must be 2D, got ndim={arr.ndim} shape={arr.shape}'
        )
    if arr.shape[0] != len(docs):
        raise ValueError(
            f'embeddings has {arr.shape[0]} rows but len(texts)={len(docs)}'
        )


def _build_cluster_model(clustering, n_topics, min_topic_size):
    if clustering == 'hdbscan':
        try:
            import hdbscan
        except ImportError as e:
            raise ImportError(
                'bertopic_fit(clustering="hdbscan") requires hdbscan '
                '(uv pip install hdbscan).'
            ) from e
        return hdbscan.HDBSCAN(
            min_cluster_size=min_topic_size,
            prediction_data=True,
        )
    from sklearn.cluster import AgglomerativeClustering
    return AgglomerativeClustering(n_clusters=n_topics)


def _build_umap_model(n_components, n_neighbors, random_state):
    try:
        import umap
    except ImportError as e:
        raise ImportError(
            'bertopic_fit requires umap-learn (uv pip install umap-learn).'
        ) from e
    return umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        random_state=random_state,
        n_jobs=1,
        metric='cosine',
    )


def _import_bertopic():
    try:
        from bertopic import BERTopic
    except ImportError as e:
        raise ImportError(
            'bertopic_fit requires bertopic (uv pip install bertopic).'
        ) from e
    return BERTopic
