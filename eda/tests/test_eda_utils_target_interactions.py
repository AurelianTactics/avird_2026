'''Tests for eda_utils_target_interactions.

Synthetic frame with planted interaction signal lets us assert pivot math,
file-writing orchestration, and stub-tree shape without depending on the
SGO CSVs.
'''
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def interaction_df():
    '''120-row frame with one strong (feat_a, feat_b) interaction.

    Target rate is high when feat_a == 'X' AND feat_b == 'P', low elsewhere,
    so the heatmap should light up a single cell. feat_c is a noise
    categorical kept for the pairwise-orchestrator file-count test.
    feat_num is a numeric feature with a coarse positive-class shift.
    '''
    rng = np.random.default_rng(0)
    n = 120
    feat_a = rng.choice(['X', 'Y', 'Z'], size=n)
    feat_b = rng.choice(['P', 'Q', 'R'], size=n)
    feat_c = rng.choice(['M', 'N'], size=n)
    feat_num = rng.normal(size=n)
    target = ((feat_a == 'X') & (feat_b == 'P')).astype(int)
    # add a little noise so neither row nor column is fully constant
    flip = rng.random(n) < 0.05
    target = np.where(flip, 1 - target, target)
    return pd.DataFrame({
        'feat_a': feat_a,
        'feat_b': feat_b,
        'feat_c': feat_c,
        'feat_num': feat_num,
        'target': target,
    })


# ---------------------------------------------------------------------------
# target_rate_pivot
# ---------------------------------------------------------------------------
def test_target_rate_pivot_cells_in_unit_interval(interaction_df):
    from eda_utils_target_interactions import target_rate_pivot
    rate, count = target_rate_pivot(interaction_df, 'feat_a', 'feat_b', 'target')
    finite = rate.to_numpy()
    finite = finite[~np.isnan(finite)]
    assert (finite >= 0).all() and (finite <= 1).all()
    assert int(count.to_numpy().sum()) == len(interaction_df)


def test_target_rate_pivot_signal_cell_higher_than_rest(interaction_df):
    from eda_utils_target_interactions import target_rate_pivot
    rate, _ = target_rate_pivot(interaction_df, 'feat_a', 'feat_b', 'target')
    signal = rate.loc['X', 'P']
    others = rate.to_numpy()
    others = others[~np.isnan(others)]
    # the planted interaction cell should be well above the rest
    assert signal > 0.5
    # most other cells should be near zero (we flipped ~5% of labels)
    assert np.median(others) < 0.2


def test_target_rate_pivot_numeric_qcut_bucketing(interaction_df):
    from eda_utils_target_interactions import target_rate_pivot
    rate, count = target_rate_pivot(interaction_df, 'feat_num', 'feat_b',
                                    'target', max_levels=4)
    # at most 4 row-bins, exactly 3 columns from feat_b distinct values
    assert rate.shape[0] <= 4
    # rows should sort meaningfully (after string-coercion in the impl they
    # are sortable by string but at least non-empty)
    assert rate.shape[0] >= 2


def test_target_rate_pivot_missing_column_raises(interaction_df):
    from eda_utils_target_interactions import target_rate_pivot
    with pytest.raises(KeyError, match='not_a_col'):
        target_rate_pivot(interaction_df, 'not_a_col', 'feat_b', 'target')


# ---------------------------------------------------------------------------
# plot_target_rate_heatmap
# ---------------------------------------------------------------------------
def test_plot_target_rate_heatmap_returns_axes_with_title(interaction_df):
    from eda_utils_target_interactions import plot_target_rate_heatmap
    ax = plot_target_rate_heatmap(interaction_df, 'feat_a', 'feat_b', 'target')
    title = ax.get_title()
    assert 'feat_a' in title and 'feat_b' in title and 'target' in title


# ---------------------------------------------------------------------------
# pairwise_heatmaps_to_png
# ---------------------------------------------------------------------------
def test_pairwise_heatmaps_writes_choose_two_files(interaction_df, tmp_path):
    from eda_utils_target_interactions import pairwise_heatmaps_to_png
    feats = ['feat_a', 'feat_b', 'feat_c']
    # use a low min_cell_count so the small fixture doesn't get skipped
    paths = pairwise_heatmaps_to_png(interaction_df, feats, 'target',
                                     out_dir=tmp_path, min_cell_count=1)
    assert len(paths) == 3  # 3 choose 2
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0


def test_pairwise_heatmaps_skips_low_count_pairs(interaction_df, tmp_path):
    from eda_utils_target_interactions import pairwise_heatmaps_to_png
    feats = ['feat_a', 'feat_b']
    # absurdly high threshold so every cell is below it -> 0 PNGs written
    paths = pairwise_heatmaps_to_png(interaction_df, feats, 'target',
                                     out_dir=tmp_path, min_cell_count=10_000)
    assert paths == []


def test_pairwise_heatmaps_default_min_cell_count_scales_with_positive_rate(interaction_df):
    '''Default ``min_cell_count`` rises as the positive rate falls.

    With a 9.5% positive target (similar to Injury Reported), the default
    floor should be at least 30, not the absolute floor of 10.
    '''
    from eda_utils_target_interactions import pairwise_heatmaps_to_png
    # Build a 9.5%-positive variant
    df = interaction_df.copy()
    df['target'] = 0
    df.iloc[:11, df.columns.get_loc('target')] = 1
    # Run with a tmp out_dir; we only care about the printed skip log here.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        paths = pairwise_heatmaps_to_png(df, ['feat_a', 'feat_b'], 'target',
                                         out_dir=td)
    # 11 positives / 120 rows ~ 9.2% -> ceil(3/0.092) ~ 33, floor=10 -> 33
    # The frame is too small to clear that bar, so we expect 0 files.
    assert paths == []


# ---------------------------------------------------------------------------
# Stub decision tree
# ---------------------------------------------------------------------------
def test_fit_stub_tree_respects_max_depth(interaction_df):
    from eda_utils_target_interactions import fit_stub_tree
    tree, names = fit_stub_tree(interaction_df,
                                ['feat_a', 'feat_b', 'feat_c', 'feat_num'],
                                'target', max_depth=2, min_samples_leaf=5)
    assert tree.get_depth() <= 2
    assert set(names) == {'feat_a', 'feat_b', 'feat_c', 'feat_num'}


def test_stub_tree_text_mentions_a_feature(interaction_df):
    from eda_utils_target_interactions import fit_stub_tree, stub_tree_text
    tree, names = fit_stub_tree(interaction_df,
                                ['feat_a', 'feat_b', 'feat_c'],
                                'target', max_depth=2, min_samples_leaf=5)
    text = stub_tree_text(tree, names)
    assert text.strip() != ''
    assert any(n in text for n in names)


def test_stub_tree_png_writes_nonzero_file(interaction_df, tmp_path):
    from eda_utils_target_interactions import fit_stub_tree, stub_tree_png
    tree, names = fit_stub_tree(interaction_df,
                                ['feat_a', 'feat_b', 'feat_c'],
                                'target', max_depth=2, min_samples_leaf=5)
    out = tmp_path / 'tree.png'
    stub_tree_png(tree, names, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_fit_stub_tree_constant_features_doesnt_crash():
    '''All-constant features -> depth-0 tree, no exception.'''
    from eda_utils_target_interactions import fit_stub_tree
    df = pd.DataFrame({
        'a': [1] * 30, 'b': ['x'] * 30, 'target': [0] * 15 + [1] * 15,
    })
    tree, names = fit_stub_tree(df, ['a', 'b'], 'target', max_depth=3,
                                min_samples_leaf=5)
    assert tree.get_depth() == 0
    assert names == ['a', 'b']
