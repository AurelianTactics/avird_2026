'''Pure-logic tests for eda_utils_neighbors. Synthetic matrices only.'''
import numpy as np
import pandas as pd
import pytest

from eda_utils_neighbors import nearest_neighbors, neighbor_examples


def _rand(n, d, seed=0):
    return np.random.default_rng(seed).normal(size=(n, d)).astype(np.float32)


def test_happy_path_shape_and_rank_invariants():
    emb = _rand(20, 8)
    df = nearest_neighbors(emb, k=3)
    assert list(df.columns) == ['query_id', 'rank', 'neighbor_id', 'distance']
    assert len(df) == 60
    assert df['query_id'].value_counts().nunique() == 1
    assert int(df['query_id'].value_counts().iloc[0]) == 3
    assert set(df['rank'].unique()) == {1, 2, 3}
    assert (df['query_id'] != df['neighbor_id']).all()


def test_near_identical_rows_become_top_neighbors():
    base = _rand(10, 8)
    base[0] = base[1] + 1e-6  # near-duplicate
    df = nearest_neighbors(base, k=3)
    top1_for_0 = df[(df['query_id'] == 0) & (df['rank'] == 1)].iloc[0]
    top1_for_1 = df[(df['query_id'] == 1) & (df['rank'] == 1)].iloc[0]
    assert top1_for_0['neighbor_id'] == 1
    assert top1_for_1['neighbor_id'] == 0
    assert top1_for_0['distance'] < 1e-4


def test_k_too_large_emits_warning_and_clamps():
    emb = _rand(5, 4)
    with pytest.warns(UserWarning, match='reducing k'):
        df = nearest_neighbors(emb, k=10)
    assert len(df) == 5 * 4  # n * (n - 1)
    assert set(df['rank'].unique()) == {1, 2, 3, 4}


def test_default_ids_are_integer_positions():
    emb = _rand(5, 4)
    df = nearest_neighbors(emb, k=2)
    assert df['query_id'].dtype.kind in ('i', 'u')
    assert set(df['query_id'].unique()) == {0, 1, 2, 3, 4}


def test_string_ids_propagate():
    emb = _rand(4, 4)
    ids = ['a', 'b', 'c', 'd']
    df = nearest_neighbors(emb, ids=ids, k=2)
    # pandas 3.x uses StringDtype for string columns; pandas 2.x uses object.
    # The contract is "ids round-trip as strings," not a specific dtype.
    assert all(isinstance(v, str) for v in df['query_id'].tolist())
    assert set(df['query_id'].unique()) == set(ids)
    assert (df['neighbor_id'].isin(ids)).all()


def test_ids_length_mismatch_raises():
    emb = _rand(5, 4)
    with pytest.raises(ValueError, match='ids length'):
        nearest_neighbors(emb, ids=['a', 'b'], k=1)


def test_empty_input_raises():
    with pytest.raises(ValueError):
        nearest_neighbors(np.zeros((0, 8)), k=1)


def test_one_row_input_raises():
    with pytest.raises(ValueError, match='at least 2'):
        nearest_neighbors(np.zeros((1, 8)), k=1)


def test_1d_input_raises():
    with pytest.raises(ValueError, match='2D'):
        nearest_neighbors(np.zeros(8), k=1)


@pytest.mark.parametrize('metric', ['cosine', 'euclidean'])
def test_metric_runs_and_returns_float_distances(metric):
    emb = _rand(8, 4)
    df = nearest_neighbors(emb, k=2, metric=metric)
    assert df['distance'].dtype == np.float64
    assert df['distance'].notna().all()


# --------------------------------------------------------------------------
# neighbor_examples
# --------------------------------------------------------------------------
def test_neighbor_examples_truncates_long_text():
    df = pd.DataFrame({
        'narrative': [
            'short text',
            'x' * 500,
            'another short',
        ],
    })
    neighbors_df = pd.DataFrame({
        'query_id': [0, 0],
        'rank': [1, 2],
        'neighbor_id': [1, 2],
        'distance': [0.1, 0.2],
    })
    out = neighbor_examples(
        df, neighbors_df, query_ids=[0], text_col='narrative', max_chars=50,
    )
    assert len(out) == 2
    long_row = out[out['neighbor_id'] == 1].iloc[0]
    assert long_row['neighbor_text'].endswith('…')
    assert len(long_row['neighbor_text']) <= 50
    short_row = out[out['neighbor_id'] == 2].iloc[0]
    assert short_row['neighbor_text'] == 'another short'


def test_neighbor_examples_respects_id_col():
    df = pd.DataFrame({
        'incident_id': ['INC-1', 'INC-2', 'INC-3'],
        'narrative': ['first text', 'second text', 'third text'],
    })
    neighbors_df = pd.DataFrame({
        'query_id': ['INC-1'],
        'rank': [1],
        'neighbor_id': ['INC-2'],
        'distance': [0.05],
    })
    out = neighbor_examples(
        df, neighbors_df, query_ids=['INC-1'],
        text_col='narrative', id_col='incident_id',
    )
    assert out.iloc[0]['query_text'] == 'first text'
    assert out.iloc[0]['neighbor_text'] == 'second text'
