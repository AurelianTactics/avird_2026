'''Dispatch + validation tests for eda_utils_bertopic.

A real BERTopic fit involves UMAP + HDBSCAN over the corpus and takes far
too long for pytest. We exercise only the wrapper's validation and the
dispatch into the correct cluster-model class via a capturing stub.
'''
import numpy as np
import pytest


# --------------------------------------------------------------------------
# Stub plumbing
# --------------------------------------------------------------------------
class _CaptureSignal(Exception):
    pass


def _make_capture_cls():
    '''Returns a fresh BERTopic-shaped class whose __init__ records kwargs.

    Constructing the class records the constructor arguments on the class
    itself, then raises ``_CaptureSignal`` so the test does not run the
    expensive fit.
    '''
    class CaptureBERTopic:
        last_kwargs = None

        def __init__(self, **kwargs):
            CaptureBERTopic.last_kwargs = kwargs
            raise _CaptureSignal()

    return CaptureBERTopic


# --------------------------------------------------------------------------
# Validation tests
# --------------------------------------------------------------------------
def test_unknown_clustering_raises():
    from eda_utils_bertopic import bertopic_fit
    with pytest.raises(ValueError, match='hdbscan'):
        bertopic_fit(
            texts=['a', 'b'], embeddings=np.zeros((2, 8)),
            clustering='unknown',
        )


def test_agglomerative_without_n_topics_raises():
    from eda_utils_bertopic import bertopic_fit
    with pytest.raises(ValueError, match='n_topics'):
        bertopic_fit(
            texts=['a', 'b'], embeddings=np.zeros((2, 8)),
            clustering='agglomerative',
        )


def test_row_mismatch_raises_before_bertopic_constructed():
    from eda_utils_bertopic import bertopic_fit
    Capture = _make_capture_cls()
    with pytest.raises(ValueError, match='embeddings'):
        bertopic_fit(
            texts=['a', 'b', 'c'],
            embeddings=np.zeros((2, 8)),  # mismatched
            clustering='hdbscan',
            _bertopic_cls=Capture,
            _umap_model='STUB',
        )
    # BERTopic was never constructed
    assert Capture.last_kwargs is None


def test_1d_embeddings_raises():
    from eda_utils_bertopic import bertopic_fit
    with pytest.raises(ValueError, match='2D'):
        bertopic_fit(
            texts=['a'], embeddings=np.zeros(8), clustering='hdbscan',
        )


# --------------------------------------------------------------------------
# Dispatch tests
# --------------------------------------------------------------------------
def test_agglomerative_dispatch_uses_agglomerative_cluster_model():
    from sklearn.cluster import AgglomerativeClustering
    from eda_utils_bertopic import bertopic_fit

    Capture = _make_capture_cls()
    with pytest.raises(_CaptureSignal):
        bertopic_fit(
            texts=['a', 'b', 'c'],
            embeddings=np.zeros((3, 8)),
            clustering='agglomerative',
            n_topics=2,
            _bertopic_cls=Capture,
            _umap_model='STUB',
        )

    cluster_model = Capture.last_kwargs['hdbscan_model']
    assert isinstance(cluster_model, AgglomerativeClustering)
    assert cluster_model.n_clusters == 2
    assert Capture.last_kwargs['embedding_model'] is None
    assert Capture.last_kwargs['umap_model'] == 'STUB'


def test_hdbscan_dispatch_uses_hdbscan_cluster_model():
    import hdbscan
    from eda_utils_bertopic import bertopic_fit

    Capture = _make_capture_cls()
    with pytest.raises(_CaptureSignal):
        bertopic_fit(
            texts=['a', 'b', 'c'],
            embeddings=np.zeros((3, 8)),
            clustering='hdbscan',
            min_topic_size=5,
            _bertopic_cls=Capture,
            _umap_model='STUB',
        )

    cluster_model = Capture.last_kwargs['hdbscan_model']
    assert isinstance(cluster_model, hdbscan.HDBSCAN)
    assert cluster_model.min_cluster_size == 5


# --------------------------------------------------------------------------
# topic_keywords_table over a tiny stub topic model
# --------------------------------------------------------------------------
class StubFittedTopicModel:
    def __init__(self):
        import pandas as pd
        self._info = pd.DataFrame({
            'Topic': [-1, 0, 1],
            'Count': [3, 12, 7],
            'Name': ['outliers', 'crashes', 'pedestrians'],
        })
        self._topics = {
            -1: [],
            0: [('rear', 0.4), ('end', 0.3), ('stopped', 0.2)],
            1: [('pedestrian', 0.5), ('crosswalk', 0.3)],
        }

    def get_topic_info(self):
        return self._info

    def get_topic(self, topic_id):
        return self._topics.get(topic_id, [])


def test_topic_keywords_table_shape():
    from eda_utils_bertopic import topic_keywords_table
    df = topic_keywords_table(StubFittedTopicModel(), top_n=10)
    assert list(df.columns) == ['topic_id', 'size', 'top_words', 'top_weights']
    assert len(df) == 3
    row0 = df[df['topic_id'] == 0].iloc[0]
    assert row0['size'] == 12
    assert row0['top_words'] == 'rear, end, stopped'
    assert row0['top_weights'] == [0.4, 0.3, 0.2]
    assert df[df['topic_id'] == -1].iloc[0]['top_words'] == ''
