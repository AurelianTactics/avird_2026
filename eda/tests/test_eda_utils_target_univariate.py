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


def test_default_feature_columns_drops_all_other_derived_targets_incl_sv_speed():
    '''Regression: every OTHER derived target -- including the templated
    ``SV Speed >= 15`` column the old static list omitted -- must be dropped
    from the feature set so it cannot leak into the ranking / SHAP.'''
    from eda_utils_target_univariate import default_feature_columns
    target_col = 'Injury Reported'
    derived_targets = [
        'No Injury Reported', 'Injury Reported', 'Multi Class Injury',
        'Binary Airbag Deployed', 'Binary Vehicle Towed',
        'SV Speed >= 15', 'Potential Non-Trivial Accident',
    ]
    cols = derived_targets + ['Highest Injury Severity Alleged',
                              'Crash With', 'master_entity']
    df = pd.DataFrame({c: [0, 1] for c in cols})
    feats = default_feature_columns(df, target_col)
    for t in derived_targets:
        assert t not in feats, f'{t!r} leaked into the feature set'
    # the target's own source column is dropped too
    assert 'Highest Injury Severity Alleged' not in feats
    # genuine pre-incident features survive
    assert 'Crash With' in feats
    assert 'master_entity' in feats


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
def test_value_counts_by_target_is_wide_with_pos_rate_share_and_count(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    out = value_counts_by_target(synth_df, 'perfect_cat', 'target')
    # Flat columns, pos_rate first, then shares, then counts.
    assert list(out.columns) == [
        'pos_rate',
        'share_within_target=0', 'share_within_target=1',
        'count=0', 'count=1',
    ]
    assert out.index.name == 'feature_value'
    # share sums to 1.0 down each target column
    assert out['share_within_target=0'].sum() == pytest.approx(1.0)
    assert out['share_within_target=1'].sum() == pytest.approx(1.0)


def test_value_counts_by_target_pos_rate_is_per_feature_value(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    # 'A' occurs only when target == 1 -> pos_rate 1.0; 'B' only when 0 -> 0.0.
    out = value_counts_by_target(synth_df, 'perfect_cat', 'target')
    assert out.loc['A', 'pos_rate'] == pytest.approx(1.0)
    assert out.loc['B', 'pos_rate'] == pytest.approx(0.0)


def test_value_counts_by_target_pos_rate_nan_when_label_absent(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    # positive_label not present in the target column -> pos_rate undefined.
    out = value_counts_by_target(synth_df, 'perfect_cat', 'target',
                                 positive_label=99)
    assert out['pos_rate'].isna().all()


def test_value_counts_by_target_sorted_by_total_count_desc():
    from eda_utils_target_univariate import value_counts_by_target
    # 'zzz' dominates but sorts LAST alphabetically -- proves the ordering is
    # by frequency, not name, so head(n) wouldn't cut off the dominant level.
    df = pd.DataFrame({
        'feat': ['zzz'] * 30 + ['aaa'] * 5 + ['mmm'] * 1,
        'tgt': [0, 1] * 18,
    })
    out = value_counts_by_target(df, 'feat', 'tgt')
    assert out.index[0] == 'zzz'
    totals = (out['count=0'] + out['count=1']).tolist()
    assert totals == sorted(totals, reverse=True)


def test_value_counts_by_target_single_value_feature_one_row(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    out = value_counts_by_target(synth_df, 'single_val_num', 'target')
    # 1 distinct feature value = 1 row in the wide table
    assert len(out) == 1


def test_value_counts_by_target_absent_value_is_zero_not_nan(synth_df):
    from eda_utils_target_univariate import value_counts_by_target
    # 'A' only occurs when target == 1, so its count/share for target 0 is 0.
    out = value_counts_by_target(synth_df, 'perfect_cat', 'target')
    assert out.loc['A', 'count=0'] == 0
    assert out.loc['A', 'share_within_target=0'] == 0.0
    assert out.loc['A', 'count=1'] == 50


def test_describe_by_target_returns_per_target_columns(synth_df):
    from eda_utils_target_univariate import describe_by_target
    out = describe_by_target(synth_df, 'perfect_num', 'target')
    assert set(out.columns) == {0, 1}
    assert 'mean' in out.index
    # planted signal: positive class mean ~ 2, negative class mean ~ 0
    assert out.loc['mean', 1] > out.loc['mean', 0]


def test_basic_eda_by_target_returns_frames_without_writing(synth_df):
    from eda_utils_target_univariate import basic_eda_by_target
    feats = ['perfect_num', 'perfect_cat']
    results = basic_eda_by_target(synth_df, 'target', feats, show=False)
    assert set(results) == set(feats)
    for feat in feats:
        assert set(results[feat]) == {'value_counts', 'describe'}
        assert not results[feat]['value_counts'].empty
        assert not results[feat]['describe'].empty


def test_basic_eda_by_target_writes_csvs_when_out_dir_given(synth_df, tmp_path):
    from eda_utils_target_univariate import basic_eda_by_target
    out_dir = tmp_path / 'basic'
    feats = ['perfect_num', 'perfect_cat']
    basic_eda_by_target(synth_df, 'target', feats, out_dir=out_dir, show=False)
    assert out_dir.exists()
    written = sorted(p.name for p in out_dir.glob('*.csv'))
    # 2 features * 2 files each
    assert len(written) == 4
    for p in out_dir.glob('*.csv'):
        assert p.stat().st_size > 0


def test_basic_eda_by_target_skips_missing_columns(synth_df):
    from eda_utils_target_univariate import basic_eda_by_target
    results = basic_eda_by_target(
        synth_df, 'target', ['perfect_num', 'not_a_column'], show=False)
    assert set(results) == {'perfect_num'}


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


def test_score_mutual_info_near_unique_categorical_returns_nan():
    '''Near-unique categoricals (IDs, raw timestamps) overfit discrete MI;
    the guard returns NaN instead of an inflated score.'''
    from eda_utils_target_univariate import _score_mutual_info
    target = pd.Series([0] * 50 + [1] * 50)
    near_unique = pd.Series([f'id_{i}' for i in range(100)])
    mi, n_used = _score_mutual_info(near_unique, target, discrete=True)
    assert n_used == 100
    assert np.isnan(mi)


def test_rank_features_datetime_scored_as_numeric_not_inflated():
    '''Datetime columns are scored on the numeric track (meaningful AUC),
    not as near-unique categoricals (which inflated discrete MI to ~0.7 on
    pure noise).'''
    from eda_utils_target_univariate import rank_features, _classify_dtype
    rng = np.random.default_rng(0)
    n = 120
    target = np.array([0] * 60 + [1] * 60)
    dates = pd.to_datetime('2024-01-01') + pd.to_timedelta(
        rng.integers(0, 365, n), unit='D')
    df = pd.DataFrame({'when': dates, 'target': target})
    assert _classify_dtype(df['when']) == 'numeric'
    out = rank_features(df, 'target', ['when'])
    row = out.iloc[0]
    # numeric track: AUC present, chi2 (categorical-only) is NaN
    assert not np.isnan(row['auc'])
    assert np.isnan(row['chi2_p'])
    # noise dates must not produce a near-perfect MI
    assert np.isnan(row['mutual_info']) or row['mutual_info'] < 0.2


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

    expected = ['feature', 'dtype', 'n_non_null', 'n_unique',
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
