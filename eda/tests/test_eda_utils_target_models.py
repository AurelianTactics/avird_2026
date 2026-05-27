'''Tests for the dependency-light helpers in eda_utils_target_models.

These cover the pure-logic helpers that do NOT require lightgbm or shap --
column-name sanitization, the SHAP return-shape dispatch, rare-bucketing,
frame preparation, and evaluation -- so they run without the heavy deps.
The LightGBM / SHAP model-fitting functions themselves remain
notebook-exercised per the plan (R10); this file guards the surrounding logic
that a SHAP/LightGBM version bump could silently break.
'''
import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# _positive_class_shap_values -- SHAP return-shape dispatch
# ---------------------------------------------------------------------------
def test_positive_class_shap_values_list_of_arrays():
    from eda_utils_target_models import _positive_class_shap_values
    neg = np.zeros((5, 3))
    pos = np.ones((5, 3))
    out = _positive_class_shap_values([neg, pos], feature_count=3)
    assert np.array_equal(out, pos)


def test_positive_class_shap_values_ndim3_picks_positive_class():
    from eda_utils_target_models import _positive_class_shap_values
    arr = np.zeros((5, 3, 2))
    arr[:, :, 1] = 7.0
    out = _positive_class_shap_values(arr, feature_count=3)
    assert out.shape == (5, 3)
    assert (out == 7.0).all()


def test_positive_class_shap_values_ndim2_passthrough():
    from eda_utils_target_models import _positive_class_shap_values
    arr = np.arange(15).reshape(5, 3).astype(float)
    out = _positive_class_shap_values(arr, feature_count=3)
    assert np.array_equal(out, arr)


def test_positive_class_shap_values_explanation_object():
    from eda_utils_target_models import _positive_class_shap_values
    arr = np.ones((4, 2))
    explanation = type('Expl', (), {'values': arr})()
    out = _positive_class_shap_values(explanation, feature_count=2)
    assert np.array_equal(out, arr)


def test_positive_class_shap_values_bad_shape_raises():
    from eda_utils_target_models import _positive_class_shap_values
    with pytest.raises(ValueError):
        _positive_class_shap_values(np.ones(5), feature_count=5)


# ---------------------------------------------------------------------------
# _sanitize_lgbm_columns + _apply_lgbm_name_map round-trip
# ---------------------------------------------------------------------------
def test_sanitize_lgbm_columns_disambiguates_collisions():
    from eda_utils_target_models import _sanitize_lgbm_columns
    # both names sanitize to the same base ('CP_SV feat') -> must disambiguate
    X = pd.DataFrame({'CP/SV feat?': [1, 2], 'CP:SV feat?': [3, 4]})
    X_safe, cat_safe, rev_map = _sanitize_lgbm_columns(X, [])
    assert len(set(X_safe.columns)) == 2
    assert set(rev_map.values()) == {'CP/SV feat?', 'CP:SV feat?'}
    # rev_map keys (sanitized) align 1:1 and in order with the renamed columns
    assert list(rev_map.keys()) == list(X_safe.columns)


def test_sanitize_lgbm_columns_identity_when_clean():
    from eda_utils_target_models import _sanitize_lgbm_columns
    X = pd.DataFrame({'speed': [1.0], 'count': [2.0]})
    X_safe, cat_safe, rev_map = _sanitize_lgbm_columns(X, ['count'])
    assert list(X_safe.columns) == ['speed', 'count']
    assert rev_map == {'speed': 'speed', 'count': 'count'}
    assert cat_safe == ['count']


def test_apply_lgbm_name_map_renames_to_sanitized():
    from eda_utils_target_models import _apply_lgbm_name_map
    model = type('M', (), {'_orig_feature_name_map_': {'CP_SV feat': 'CP/SV feat?'}})()
    X = pd.DataFrame({'CP/SV feat?': [1, 2]})
    out = _apply_lgbm_name_map(model, X)
    assert list(out.columns) == ['CP_SV feat']


def test_apply_lgbm_name_map_noop_without_map():
    from eda_utils_target_models import _apply_lgbm_name_map
    X = pd.DataFrame({'a': [1]})
    assert _apply_lgbm_name_map(object(), X) is X


# ---------------------------------------------------------------------------
# RareBucketer
# ---------------------------------------------------------------------------
def test_rare_bucketer_buckets_below_threshold_and_unseen():
    from eda_utils_target_models import RareBucketer
    X = pd.DataFrame({'col': ['a', 'a', 'a', 'b', 'b', 'rare']})
    rb = RareBucketer(threshold=3).fit(X)
    out = rb.transform(X)
    assert list(out['col']) == ['a', 'a', 'a', '__OTHER__', '__OTHER__', '__OTHER__']
    # unseen category at transform time maps to __OTHER__
    out2 = rb.transform(pd.DataFrame({'col': ['a', 'zzz']}))
    assert list(out2['col']) == ['a', '__OTHER__']


def test_rare_bucketer_feature_names_out():
    from eda_utils_target_models import RareBucketer
    X = pd.DataFrame({'c1': ['a'] * 5, 'c2': ['b'] * 5})
    rb = RareBucketer(threshold=1).fit(X)
    assert list(rb.get_feature_names_out()) == ['c1', 'c2']


# ---------------------------------------------------------------------------
# prepare_modeling_frame
# ---------------------------------------------------------------------------
def test_prepare_modeling_frame_dtype_dispatch_and_imputation():
    from eda_utils_target_models import prepare_modeling_frame
    df = pd.DataFrame({
        'num': [1.0, 2.0, np.nan, 4.0],
        'allnan': [np.nan, np.nan, np.nan, np.nan],
        'flag': [True, False, True, False],
        'cat': ['x', 'y', None, 'x'],
        'tgt': [0, 1, 0, 1],
    })
    X, y, cat_cols, num_cols = prepare_modeling_frame(
        df, 'tgt', feature_cols=['num', 'allnan', 'flag', 'cat'])
    assert cat_cols == ['cat']
    assert set(num_cols) == {'num', 'allnan', 'flag'}
    # numeric NaN -> median of [1, 2, 4] = 2.0
    assert X['num'].isna().sum() == 0
    assert X['num'].iloc[2] == pytest.approx(2.0)
    # all-NaN numeric -> 0.0
    assert (X['allnan'] == 0.0).all()
    # bool -> float
    assert X['flag'].tolist() == [1.0, 0.0, 1.0, 0.0]
    # object -> category with the __MISSING__ sentinel for the None
    assert str(X['cat'].dtype) == 'category'
    assert '__MISSING__' in list(X['cat'])
    # threshold recorded on attrs
    assert X.attrs['categorical_threshold'] == 30
    assert y.tolist() == [0, 1, 0, 1]


def test_prepare_modeling_frame_raises_for_missing_target():
    from eda_utils_target_models import prepare_modeling_frame
    df = pd.DataFrame({'a': [1, 2]})
    with pytest.raises(KeyError):
        prepare_modeling_frame(df, 'tgt', feature_cols=['a'])


# ---------------------------------------------------------------------------
# fit_logistic + evaluate_classifier + feature_importance_logistic
# (sklearn only -- no lightgbm / shap)
# ---------------------------------------------------------------------------
@pytest.fixture
def separable_frame():
    rng = np.random.default_rng(0)
    n = 200
    y = np.array([0] * 100 + [1] * 100)
    num = np.where(y == 1, rng.normal(2.0, 0.5, n), rng.normal(0.0, 0.5, n))
    cat = np.where(y == 1, 'A', 'B')
    return pd.DataFrame({'num': num, 'cat': cat, 'tgt': y})


def test_fit_logistic_pipeline_separates_and_reports_importance(separable_frame):
    from eda_utils_target_models import (
        prepare_modeling_frame, stratified_split, fit_logistic,
        evaluate_classifier, feature_importance_logistic,
    )
    X, y, cat_cols, num_cols = prepare_modeling_frame(
        separable_frame, 'tgt', feature_cols=['num', 'cat'])
    X_tr, X_te, y_tr, y_te = stratified_split(X, y, random_state=0)
    pipe = fit_logistic(X_tr, y_tr, cat_cols, num_cols)
    res = evaluate_classifier(pipe, X_te, y_te, 'lr')
    assert res['name'] == 'lr'
    assert res['auc'] > 0.8
    assert res['n_test'] == len(y_te)
    imp = feature_importance_logistic(pipe)
    assert set(imp.columns) == {'feature', 'coef', 'abs_coef'}
    assert (imp['abs_coef'] >= 0).all()


def test_evaluate_classifier_single_class_holdout_returns_nan_auc():
    from eda_utils_target_models import evaluate_classifier

    class ConstModel:
        def predict_proba(self, X):
            n = len(X)
            return np.column_stack([np.full(n, 0.5), np.full(n, 0.5)])

    res = evaluate_classifier(ConstModel(), pd.DataFrame({'a': [1, 2, 3]}),
                              pd.Series([1, 1, 1]), 'const')
    assert np.isnan(res['auc'])
    assert res['n_pos_test'] == 3
    assert res['n_test'] == 3
