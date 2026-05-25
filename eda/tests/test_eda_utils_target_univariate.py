'''Tests for eda_utils_target_univariate.

Synthetic 100-row frame with a planted signal lets us assert each scorer
against a known ground truth without depending on the SGO CSVs.
'''
import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synth_df():
    '''100-row frame with planted signals + degenerate columns.

    * ``perfect_num``      -- positive class mean shifted; high AUC, +1 dir.
    * ``inverse_num``      -- positive class mean shifted DOWN; high AUC, -1 dir.
    * ``perfect_cat``      -- value 'A' iff target == 1; near-perfect chi-sq.
    * ``noise_num``        -- pure noise.
    * ``all_nan_num``      -- entirely NaN.
    * ``single_val_num``   -- zero variance.
    * ``target``           -- 50/50 binary (so every metric is well-defined).
    '''
    rng = np.random.default_rng(0)
    n = 100
    target = np.array([0] * 50 + [1] * 50)
    perfect_num = np.where(target == 1, rng.normal(2.0, 0.5, n),
                                       rng.normal(0.0, 0.5, n))
    inverse_num = np.where(target == 1, rng.normal(-2.0, 0.5, n),
                                       rng.normal(0.0, 0.5, n))
    noise_num = rng.normal(0.0, 1.0, n)
    perfect_cat = np.where(target == 1, 'A', 'B')
    all_nan_num = np.array([np.nan] * n)
    single_val_num = np.array([7.0] * n)

    return pd.DataFrame({
        'perfect_num': perfect_num,
        'inverse_num': inverse_num,
        'perfect_cat': perfect_cat,
        'noise_num': noise_num,
        'all_nan_num': all_nan_num,
        'single_val_num': single_val_num,
        'target': target,
    })


# ---------------------------------------------------------------------------
# default_feature_columns + drop-list contract
# ---------------------------------------------------------------------------
def test_default_feature_columns_drops_target_and_source():
    from eda_utils_target_univariate import (
        DEFAULT_DROP_COLS, TARGET_SOURCE_COLS, default_feature_columns,
    )
    # Build a frame containing every name in the drop-list plus the source
    # column of the target. None of them should survive.
    target_col = 'Injury Reported'
    cols_present = (
        list(DEFAULT_DROP_COLS)
        + list(TARGET_SOURCE_COLS[target_col])
        + [target_col, 'kept_one', 'kept_two']
    )
    df = pd.DataFrame({c: [0, 1] for c in cols_present})
    feats = default_feature_columns(df, target_col)
    assert set(feats) == {'kept_one', 'kept_two'}


def test_default_feature_columns_unknown_target_falls_back_to_static_only():
    from eda_utils_target_univariate import default_feature_columns
    df = pd.DataFrame({
        'NotATarget': [0, 1],
        'Highest Injury Severity Alleged': [0, 1],  # not dropped for unknown target
        'feat_a': [1, 2],
    })
    feats = default_feature_columns(df, 'NotATarget')
    assert 'NotATarget' not in feats
    assert 'feat_a' in feats
    # 'Highest Injury Severity Alleged' is NOT in DEFAULT_DROP_COLS so it
    # survives when the target is not registered in TARGET_SOURCE_COLS.
    assert 'Highest Injury Severity Alleged' in feats


def test_default_feature_columns_airbag_target_drops_three_source_cols():
    from eda_utils_target_univariate import default_feature_columns
    df = pd.DataFrame({
        'Binary Airbag Deployed': [0, 1],
        'Any Air Bags Deployed?': ['No', 'Yes'],
        'CP Any Air Bags Deployed?': ['No', 'Yes'],
        'SV Any Air Bags Deployed?': ['No', 'Yes'],
        'other': [1, 2],
    })
    feats = default_feature_columns(df, 'Binary Airbag Deployed')
    assert feats == ['other']


def test_default_feature_columns_extra_drop_extends_drop_set(synth_df):
    from eda_utils_target_univariate import default_feature_columns
    feats = default_feature_columns(synth_df, 'target', extra_drop=('noise_num',))
    assert 'noise_num' not in feats
    assert 'perfect_num' in feats


def test_default_feature_columns_raises_for_missing_target(synth_df):
    from eda_utils_target_univariate import default_feature_columns
    with pytest.raises(KeyError, match='NotAColumn'):
        default_feature_columns(synth_df, 'NotAColumn')


# ---------------------------------------------------------------------------
# Basic-EDA helpers
# ---------------------------------------------------------------------------
def test_value_counts_by_target_share_sums_to_one_per_target(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    out = value_counts_by_target(synth_df, 'perfect_cat', 'target')
    assert set(out.columns) == {'feature_value', 'target_value', 'count',
                                'share_within_target'}
    for tval, grp in out.groupby('target_value'):
        assert grp['share_within_target'].sum() == pytest.approx(1.0)


def test_value_counts_by_target_single_value_feature_does_not_raise(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    out = value_counts_by_target(synth_df, 'single_val_num', 'target')
    # 1 distinct value x 2 target values = 2 rows
    assert len(out) == 2


def test_describe_by_target_returns_per_target_columns(synth_df):
    from eda_utils_target_univariate import describe_by_target
    out = describe_by_target(synth_df, 'perfect_num', 'target')
    assert set(out.columns) == {0, 1}
    assert 'mean' in out.index
    # planted signal: positive class mean ~ 2, negative class mean ~ 0
    assert out.loc['mean', 1] > out.loc['mean', 0]


def test_basic_eda_to_csvs_creates_files(synth_df, tmp_path):
    from eda_utils_target_univariate import basic_eda_to_csvs
    out_dir = tmp_path / 'basic'
    feats = ['perfect_num', 'perfect_cat']
    paths = basic_eda_to_csvs(synth_df, 'target', feats, out_dir)
    assert out_dir.exists()
    # 2 features * 2 files each
    assert len(paths) == 4
    for p in paths:
        assert p.exists()
        assert p.stat().st_size > 0


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------
def test_score_auc_positive_direction(synth_df):
    from eda_utils_target_univariate import _score_auc
    mag, direction, n_used = _score_auc(synth_df['perfect_num'], synth_df['target'])
    assert n_used == 100
    assert mag > 0.95
    assert direction == 1


def test_score_auc_negative_direction(synth_df):
    from eda_utils_target_univariate import _score_auc
    mag, direction, n_used = _score_auc(synth_df['inverse_num'], synth_df['target'])
    assert n_used == 100
    assert mag > 0.95
    assert direction == -1


def test_score_auc_all_nan_returns_nan(synth_df):
    from eda_utils_target_univariate import _score_auc
    mag, direction, n_used = _score_auc(synth_df['all_nan_num'], synth_df['target'])
    assert n_used == 0
    assert np.isnan(mag)
    assert np.isnan(direction)


def test_score_auc_single_value_returns_nan(synth_df):
    from eda_utils_target_univariate import _score_auc
    mag, direction, n_used = _score_auc(synth_df['single_val_num'], synth_df['target'])
    assert n_used == 100
    assert np.isnan(mag)
    assert np.isnan(direction)


def test_score_ks_separates_classes(synth_df):
    from eda_utils_target_univariate import _score_ks
    ks, n_used = _score_ks(synth_df['perfect_num'], synth_df['target'])
    assert n_used == 100
    assert ks > 0.9


def test_score_mutual_info_numeric_signal_beats_noise(synth_df):
    from eda_utils_target_univariate import _score_mutual_info
    mi_signal, _ = _score_mutual_info(synth_df['perfect_num'], synth_df['target'], discrete=False)
    mi_noise, _ = _score_mutual_info(synth_df['noise_num'], synth_df['target'], discrete=False)
    assert mi_signal > mi_noise


def test_score_mutual_info_categorical_perfect_signal(synth_df):
    from eda_utils_target_univariate import _score_mutual_info
    mi, n_used = _score_mutual_info(synth_df['perfect_cat'], synth_df['target'], discrete=True)
    assert n_used == 100
    assert mi > 0.3


def test_score_chi2_perfect_cat_near_zero_p(synth_df):
    from eda_utils_target_univariate import _score_chi2
    p, chi2, n_used = _score_chi2(synth_df['perfect_cat'], synth_df['target'])
    assert n_used == 100
    assert p < 1e-10


def test_score_correlation_positive(synth_df):
    from eda_utils_target_univariate import _score_correlation
    rho, n_used = _score_correlation(synth_df['perfect_num'], synth_df['target'])
    assert n_used == 100
    assert rho > 0.8


def test_score_correlation_negative(synth_df):
    from eda_utils_target_univariate import _score_correlation
    rho, _ = _score_correlation(synth_df['inverse_num'], synth_df['target'])
    assert rho < -0.8


# ---------------------------------------------------------------------------
# rank_features end-to-end
# ---------------------------------------------------------------------------
def test_rank_features_columns_and_order(synth_df):
    from eda_utils_target_univariate import rank_features
    feats = ['perfect_num', 'inverse_num', 'perfect_cat',
             'noise_num', 'all_nan_num', 'single_val_num']
    out = rank_features(synth_df, 'target', feats)

    expected = ['feature', 'dtype', 'n_non_null',
                'auc', 'auc_direction', 'ks',
                'mutual_info', 'chi2_p', 'correlation']
    assert list(out.columns) == expected
    assert len(out) == len(feats)

    # noise should rank below the planted signals
    pos = out.set_index('feature')['mutual_info']
    assert pos['perfect_num'] > pos['noise_num']
    assert pos['perfect_cat'] > pos['noise_num']


def test_rank_features_all_nan_row_is_all_nan(synth_df):
    from eda_utils_target_univariate import rank_features
    out = rank_features(synth_df, 'target', ['all_nan_num'])
    row = out.iloc[0]
    assert row['n_non_null'] == 0
    assert np.isnan(row['auc'])
    assert np.isnan(row['ks'])
    assert np.isnan(row['mutual_info']) or row['mutual_info'] == 0.0
    assert np.isnan(row['correlation'])


def test_rank_features_categorical_chi2_set_auc_nan(synth_df):
    from eda_utils_target_univariate import rank_features
    out = rank_features(synth_df, 'target', ['perfect_cat'])
    row = out.iloc[0]
    assert np.isnan(row['auc'])
    assert np.isnan(row['auc_direction'])
    assert np.isnan(row['ks'])
    assert not np.isnan(row['chi2_p'])
    assert row['chi2_p'] < 1e-10


def test_rank_features_raises_for_missing_target(synth_df):
    from eda_utils_target_univariate import rank_features
    with pytest.raises(KeyError, match='NotATarget'):
        rank_features(synth_df, 'NotATarget', ['perfect_num'])
