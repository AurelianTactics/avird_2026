'''Validation + tiny-input smoke tests for eda_utils_emb_cluster.

UMAP itself is slow to import (numba JIT) and slow to fit; we keep tests
to small synthetic matrices so the suite stays under a few seconds.
The plotting helper is intentionally not asserted on; the notebook is the
visual surface.
'''
import numpy as np
import pytest

from eda_utils_emb_cluster import umap_project, agglomerative_cluster


def _rand(n, d, seed=0):
    return np.random.default_rng(seed).normal(size=(n, d)).astype(np.float32)


# --------------------------------------------------------------------------
# umap_project
# --------------------------------------------------------------------------
@pytest.mark.parametrize('n_components', [2, 5])
def test_umap_project_returns_correct_shape(n_components):
    emb = _rand(50, 16)
    coords = umap_project(emb, n_components=n_components, n_neighbors=10)
    assert coords.shape == (50, n_components)
    assert np.isfinite(coords).all()


def test_umap_project_deterministic_with_fixed_seed():
    emb = _rand(40, 16)
    a = umap_project(emb, n_components=2, n_neighbors=8, random_state=0)
    b = umap_project(emb, n_components=2, n_neighbors=8, random_state=0)
    np.testing.assert_array_equal(a, b)


def test_umap_project_1d_input_raises():
    with pytest.raises(ValueError, match='2D'):
        umap_project(np.zeros(16))


# --------------------------------------------------------------------------
# agglomerative_cluster
# --------------------------------------------------------------------------
def test_agglomerative_returns_int_array_with_requested_clusters():
    emb = _rand(30, 8)
    labels = agglomerative_cluster(emb, n_clusters=5)
    assert labels.shape == (30,)
    assert labels.dtype == int
    assert len(set(labels.tolist())) == 5


def test_agglomerative_distance_threshold_path():
    emb = _rand(30, 8)
    labels = agglomerative_cluster(
        emb, distance_threshold=1.5, linkage='average', metric='cosine',
    )
    assert labels.shape == (30,)
    assert labels.dtype == int


def test_agglomerative_both_args_set_raises():
    emb = _rand(10, 8)
    with pytest.raises(ValueError, match='n_clusters.*distance_threshold|distance_threshold.*n_clusters'):
        agglomerative_cluster(emb, n_clusters=3, distance_threshold=0.5)


def test_agglomerative_neither_arg_set_raises():
    emb = _rand(10, 8)
    with pytest.raises(ValueError, match='n_clusters'):
        agglomerative_cluster(emb)


def test_agglomerative_1d_input_raises():
    with pytest.raises(ValueError, match='2D'):
        agglomerative_cluster(np.zeros(8), n_clusters=2)


def test_ward_requires_euclidean_surface_sklearn_error():
    emb = _rand(20, 8)
    with pytest.raises(ValueError):
        agglomerative_cluster(
            emb, n_clusters=3, linkage='ward', metric='cosine',
        )
