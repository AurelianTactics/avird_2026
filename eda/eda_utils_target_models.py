'''
EDA utils - quick model fits against a binary target column.

Three model fits, one shared evaluation contract:

* ``fit_lgbm_rf``      -- LightGBM random forest (``boosting_type='rf'``)
* ``fit_logistic``     -- sklearn LogisticRegression with one-hot + scale
* ``fit_lgbm_gbm``     -- LightGBM gradient boosting (``boosting_type='gbdt'``)

All three return a trained estimator; ``evaluate_classifier`` produces the
shared eval dict; per-model feature-importance helpers extract gain/coef
tables. The SHAP-based importance + summary plot live in
``shap_importance`` / ``shap_summary_plot`` (added alongside the GBM fit).

Class imbalance is handled via built-in weights -- ``is_unbalance=True`` for
LightGBM and ``class_weight='balanced'`` for LogisticRegression. No SMOTE
in v1 (avoids adding imbalanced-learn as a dep).

Categorical handling: ``prepare_modeling_frame`` casts object-dtype features
to pandas ``category`` dtype once at the top so LightGBM can consume them
natively via ``categorical_feature='auto'``. The logistic regression
pipeline owns its own one-hot + standard-scale + rare-bucket step inside
its ``ColumnTransformer`` so the shared frame stays un-bucketed -- this way
LightGBM sees full categorical cardinality (its tree splits handle that
fine) while LR collapses long-tail levels to a single ``__OTHER__`` bucket
before encoding.

Convention: helpers that take an ``out_path`` argument create the parent
directory themselves.
'''
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


# ---------------------------------------------------------------------------
# Frame preparation
# ---------------------------------------------------------------------------
_MISSING_SENTINEL = '__MISSING__'


def prepare_modeling_frame(df, target_col, feature_cols=None,
                           categorical_threshold=30):
    '''Build the ``(X, y, categorical_cols, numeric_cols)`` modeling tuple.

    * Object / string columns are cast to pandas ``category`` dtype so
      LightGBM can consume them natively via ``categorical_feature='auto'``.
    * Categorical NaN cells are filled with the ``__MISSING__`` sentinel
      level (the level is added to the category set first).
    * Numeric columns are NaN-filled with the column median.
    * ``categorical_threshold`` is carried on the returned tuple as
      metadata; the actual rare-bucketing happens *inside* the
      ``fit_logistic`` ``ColumnTransformer`` so the same ``X`` can be
      consumed by LightGBM (full cardinality) and LR (rare-bucketed) without
      maintaining two parallel frames.

    Returns:
        X  -- DataFrame of features (categoricals cast, numerics imputed)
        y  -- Series of int target values
        categorical_cols -- list of column names of dtype ``category``
        numeric_cols     -- list of column names with numeric dtype

    Raises ``KeyError`` if ``target_col`` is not a column.
    '''
    if target_col not in df.columns:
        raise KeyError(f'target_col={target_col!r} not in df')
    if feature_cols is None:
        # Lazy import to avoid a hard cycle if a caller imports this module
        # without having univariate available.
        from eda_utils_target_univariate import default_feature_columns
        feature_cols = default_feature_columns(df, target_col)

    X = df[feature_cols].copy()
    y = df[target_col].astype(int)

    categorical_cols = []
    numeric_cols = []
    for col in feature_cols:
        s = X[col]
        if pd.api.types.is_bool_dtype(s):
            X[col] = s.astype(float)
            numeric_cols.append(col)
        elif pd.api.types.is_numeric_dtype(s):
            x = pd.to_numeric(s, errors='coerce')
            if x.notna().any():
                median = float(x.median())
                X[col] = x.fillna(median)
            else:
                X[col] = x.fillna(0.0)
            numeric_cols.append(col)
        else:
            s_obj = s.astype('object').where(s.notna(), _MISSING_SENTINEL)
            X[col] = pd.Categorical(s_obj)
            categorical_cols.append(col)

    # Attach the threshold as DataFrame metadata. It's read by fit_logistic
    # below; tests can also pass it explicitly.
    X.attrs['categorical_threshold'] = int(categorical_threshold)
    return X, y, categorical_cols, numeric_cols


def stratified_split(X, y, test_size=0.2, random_state=0):
    '''Thin wrapper over sklearn's ``train_test_split`` with ``stratify=y``.

    Returns ``(X_train, X_test, y_train, y_test)`` -- every model in this
    module should use the same split for honest comparison.
    '''
    return train_test_split(X, y, test_size=test_size,
                            stratify=y, random_state=random_state)


# ---------------------------------------------------------------------------
# Rare bucketer for the LR pathway
# ---------------------------------------------------------------------------
class RareBucketer(BaseEstimator, TransformerMixin):
    '''Bucket categories whose support is below ``threshold`` into ``__OTHER__``.

    Designed to live inside a sklearn ``ColumnTransformer`` step ahead of
    ``OneHotEncoder``. Keeps the categorical *type* (object) but caps the
    cardinality LR has to fit coefficients for. Categories that appear
    fewer than ``threshold`` times in the training data are mapped to the
    ``__OTHER__`` level. Unseen categories at predict-time map to
    ``__OTHER__`` automatically.
    '''
    def __init__(self, threshold=30):
        self.threshold = threshold

    def fit(self, X, y=None):
        X = pd.DataFrame(X).copy()
        self.kept_per_col_ = {}
        for col in X.columns:
            counts = X[col].astype('object').value_counts(dropna=False)
            kept = counts[counts >= self.threshold].index.tolist()
            self.kept_per_col_[col] = set(kept)
        self.feature_names_in_ = list(X.columns)
        return self

    def transform(self, X):
        X = pd.DataFrame(X).copy()
        out = pd.DataFrame(index=X.index, columns=self.feature_names_in_)
        for col in self.feature_names_in_:
            kept = self.kept_per_col_[col]
            s = X[col].astype('object')
            out[col] = s.where(s.isin(kept), '__OTHER__')
        return out

    def get_feature_names_out(self, input_features=None):
        if input_features is None:
            return np.asarray(self.feature_names_in_)
        return np.asarray(list(input_features))


# ---------------------------------------------------------------------------
# LightGBM feature-name sanitization
# ---------------------------------------------------------------------------
# LightGBM rejects feature names containing JSON-special / control characters
# (commas, colons, quotes, brackets, slashes, question marks, whitespace
# other than space). The SGO schema has plenty of these (``CP/SV Any Air Bags
# Deployed?``, etc.) so we rewrite the names just for the LightGBM call and
# keep the mapping on the model in ``_orig_feature_name_map_`` so the
# importance helpers can restore the originals.
_LGBM_BAD_CHARS = set('",:\'[]{}()<>?\\/\t\n\r')


def _sanitize_lgbm_columns(X, categorical_cols):
    '''Return ``(X_renamed, cat_cols_renamed, name_map)`` safe for LightGBM.

    ``name_map`` is ``{sanitized: original}`` so the inverse rename can
    restore display names on the importance table.
    '''
    mapping = {}
    rev_map = {}
    for c in X.columns:
        new = ''.join('_' if ch in _LGBM_BAD_CHARS else ch for ch in str(c))
        # Collapse runs of underscores and trim trailing _ for readability
        while '__' in new:
            new = new.replace('__', '_')
        new = new.strip('_ ') or 'col'
        # Disambiguate collisions defensively
        base = new
        i = 2
        while new in rev_map:
            new = f'{base}_{i}'
            i += 1
        mapping[c] = new
        rev_map[new] = c
    if all(k == v for k, v in mapping.items()):
        return X, list(categorical_cols), {c: c for c in X.columns}
    X_renamed = X.rename(columns=mapping)
    cat_renamed = [mapping[c] for c in categorical_cols if c in mapping]
    return X_renamed, cat_renamed, rev_map


def _attach_name_map(model, rev_map):
    '''Attach a sanitized->original column-name map to a fitted LightGBM model.'''
    setattr(model, '_orig_feature_name_map_', rev_map)
    return model


# ---------------------------------------------------------------------------
# Model fits
# ---------------------------------------------------------------------------
def fit_lgbm_rf(X_train, y_train, categorical_cols,
                n_estimators=200, num_leaves=15, min_data_in_leaf=20,
                random_state=0):
    '''Fit a LightGBM random-forest classifier.

    ``boosting_type='rf'`` requires ``bagging_fraction`` and ``bagging_freq``
    to be set (LightGBM is strict here); ``feature_fraction`` is also set to
    follow standard RF practice. ``is_unbalance=True`` handles the ~9.5%
    positive rate without resampling.
    '''
    import lightgbm as lgb
    X_safe, cat_safe, rev_map = _sanitize_lgbm_columns(X_train, categorical_cols)
    model = lgb.LGBMClassifier(
        boosting_type='rf',
        n_estimators=n_estimators,
        num_leaves=num_leaves,
        min_data_in_leaf=min_data_in_leaf,
        bagging_fraction=0.8,
        bagging_freq=1,
        feature_fraction=0.8,
        is_unbalance=True,
        random_state=random_state,
        verbose=-1,
    )
    model.fit(X_safe, y_train, categorical_feature=cat_safe or 'auto')
    return _attach_name_map(model, rev_map)


def fit_logistic(X_train, y_train, categorical_cols, numeric_cols,
                 C=1.0, max_iter=2000, random_state=0,
                 rare_threshold=None):
    '''Fit a logistic regression pipeline.

    The pipeline is:
        ColumnTransformer
            categoricals -> RareBucketer -> OneHotEncoder
            numerics     -> StandardScaler
        LogisticRegression(class_weight='balanced')

    ``rare_threshold`` defaults to ``X_train.attrs['categorical_threshold']``
    if set (i.e., what ``prepare_modeling_frame`` recorded), or 30 if not.
    '''
    if rare_threshold is None:
        rare_threshold = int(X_train.attrs.get('categorical_threshold', 30))

    cat_pipeline = Pipeline(steps=[
        ('rare', RareBucketer(threshold=rare_threshold)),
        ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False)),
    ])

    transformers = []
    if categorical_cols:
        transformers.append(('cat', cat_pipeline, categorical_cols))
    if numeric_cols:
        transformers.append(('num', StandardScaler(), numeric_cols))

    pre = ColumnTransformer(transformers=transformers, remainder='drop')
    clf = LogisticRegression(
        C=C, max_iter=max_iter, class_weight='balanced',
        random_state=random_state,
    )
    pipe = Pipeline(steps=[('pre', pre), ('clf', clf)])
    pipe.fit(X_train, y_train)
    return pipe


# ---------------------------------------------------------------------------
# Evaluation + per-model importance tables
# ---------------------------------------------------------------------------
def _apply_lgbm_name_map(model, X):
    '''If ``model`` was trained with sanitized column names, rename ``X`` to match.'''
    rev_map = getattr(model, '_orig_feature_name_map_', None)
    if not rev_map:
        return X
    # rev_map is sanitized -> original; invert to original -> sanitized
    inv = {v: k for k, v in rev_map.items()}
    cols = [inv.get(c, c) for c in X.columns]
    if cols == list(X.columns):
        return X
    return X.rename(columns=dict(zip(X.columns, cols)))


def evaluate_classifier(model, X_test, y_test, name):
    '''Score ``model`` on holdout with AUC + average-precision.

    Returns a flat dict suitable for stacking into a comparison DataFrame:
        ``{name, auc, pr_auc, n_test, n_pos_test}``
    '''
    # _apply_lgbm_name_map is a no-op for models without a sanitized name map.
    X_test = _apply_lgbm_name_map(model, X_test)
    proba = model.predict_proba(X_test)[:, 1]
    y = np.asarray(y_test).astype(int)
    try:
        auc = float(roc_auc_score(y, proba))
    except ValueError:
        auc = float('nan')
    try:
        pr_auc = float(average_precision_score(y, proba))
    except ValueError:
        pr_auc = float('nan')
    return {
        'name': name,
        'auc': auc,
        'pr_auc': pr_auc,
        'n_test': int(len(y)),
        'n_pos_test': int(y.sum()),
    }


def feature_importance_lgbm(model, feature_cols=None):
    '''Tidy gain + split importance for a fitted LightGBM model.

    Returns DataFrame ``[feature, gain, split]`` sorted by gain desc.
    Works for both ``boosting_type='rf'`` and ``'gbdt'``. If the model
    was trained with sanitized column names, the originals are restored
    via ``_orig_feature_name_map_``.
    '''
    if feature_cols is None:
        feature_cols = list(model.booster_.feature_name())
    rev_map = getattr(model, '_orig_feature_name_map_', None)
    if rev_map:
        feature_cols = [rev_map.get(c, c) for c in feature_cols]
    gain = model.booster_.feature_importance(importance_type='gain')
    split = model.booster_.feature_importance(importance_type='split')
    out = pd.DataFrame({
        'feature': list(feature_cols),
        'gain': gain,
        'split': split,
    })
    return out.sort_values('gain', ascending=False).reset_index(drop=True)


def feature_importance_logistic(pipeline):
    '''Tidy ``[feature, coef, abs_coef]`` for the LR pipeline from ``fit_logistic``.

    Expands one-hot categoricals back into ``parent__value`` rows. The encoded
    feature names are read directly from the fitted ``ColumnTransformer``.
    '''
    pre = pipeline.named_steps['pre']
    clf = pipeline.named_steps['clf']

    encoded_names = list(pre.get_feature_names_out())
    coefs = clf.coef_.ravel()
    if len(encoded_names) != len(coefs):
        raise ValueError(
            f'encoded feature count ({len(encoded_names)}) does not match '
            f'coef count ({len(coefs)}); pipeline / coef shape mismatch'
        )
    out = pd.DataFrame({
        'feature': encoded_names,
        'coef': coefs,
        'abs_coef': np.abs(coefs),
    })
    return out.sort_values('abs_coef', ascending=False).reset_index(drop=True)


# ---------------------------------------------------------------------------
# LightGBM gradient boosting + SHAP
# ---------------------------------------------------------------------------
def fit_lgbm_gbm(X_train, y_train, categorical_cols,
                 n_estimators=200, num_leaves=15, learning_rate=0.05,
                 min_data_in_leaf=20, random_state=0):
    '''Fit a LightGBM gradient boosting classifier.

    ``is_unbalance=True`` for the same imbalance reason as ``fit_lgbm_rf``.
    '''
    import lightgbm as lgb
    X_safe, cat_safe, rev_map = _sanitize_lgbm_columns(X_train, categorical_cols)
    model = lgb.LGBMClassifier(
        boosting_type='gbdt',
        n_estimators=n_estimators,
        num_leaves=num_leaves,
        learning_rate=learning_rate,
        min_data_in_leaf=min_data_in_leaf,
        is_unbalance=True,
        random_state=random_state,
        verbose=-1,
    )
    model.fit(X_safe, y_train, categorical_feature=cat_safe or 'auto')
    return _attach_name_map(model, rev_map)


def _positive_class_shap_values(shap_values, feature_count):
    '''Extract the positive-class SHAP value matrix from either SHAP return shape.

    SHAP >=0.45 returns an ``Explanation`` object whose ``.values`` is either
    ``(n_rows, n_features)`` for the new single-class layout or
    ``(n_rows, n_features, 2)`` for the binary multi-output layout. Some
    older LightGBM/SHAP combos still return a list ``[neg, pos]`` of arrays.
    Pick the positive-class slice in all three cases.
    '''
    # SHAP Explanation object
    values = getattr(shap_values, 'values', shap_values)

    if isinstance(values, list):
        # Legacy list-of-arrays: [neg, pos]
        return np.asarray(values[1])

    values = np.asarray(values)
    if values.ndim == 3:
        # (n_rows, n_features, n_classes) -- pick positive class
        return values[:, :, 1]
    if values.ndim == 2:
        # Already (n_rows, n_features) for the positive class
        return values
    raise ValueError(f'unexpected SHAP values shape: {values.shape}')


def shap_importance(model, X_sample, feature_cols=None):
    '''Compute mean absolute SHAP per feature for the positive class.

    Returns DataFrame ``[feature, mean_abs_shap]`` sorted descending. SHAP is
    computed for the *positive* class (injury == 1); negating signs flips
    the interpretation. ``X_sample`` should be the dataframe LightGBM was
    trained on or a downsample thereof (TreeExplainer tolerates either).

    Per R5: SHAP is intentionally scoped to the gradient-boosting fit only.
    The RF and LR fits expose their own importance tables via
    ``feature_importance_lgbm`` and ``feature_importance_logistic``.
    '''
    import shap
    if feature_cols is None:
        feature_cols = list(X_sample.columns)

    X_sample = _apply_lgbm_name_map(model, X_sample)
    explainer = shap.TreeExplainer(model)
    explanation = explainer(X_sample)
    pos = _positive_class_shap_values(explanation, len(feature_cols))

    mean_abs = np.abs(pos).mean(axis=0)
    out = pd.DataFrame({
        'feature': list(feature_cols),
        'mean_abs_shap': mean_abs,
    })
    return out.sort_values('mean_abs_shap', ascending=False).reset_index(drop=True)


def shap_summary_plot(model, X_sample, out_path,
                      plot_type='bar', max_display=20):
    '''Render a SHAP summary plot and save it to ``out_path``.

    ``plot_type='bar'`` shows mean(|SHAP|) per feature; ``'beeswarm'`` (or
    ``'dot'``) shows the per-row distribution. Returns the absolute path
    written. Creates parent dirs as needed.
    '''
    import matplotlib.pyplot as plt
    import shap

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    X_sample = _apply_lgbm_name_map(model, X_sample)
    explainer = shap.TreeExplainer(model)
    explanation = explainer(X_sample)
    pos = _positive_class_shap_values(explanation, X_sample.shape[1])

    # shap.summary_plot(show=False) creates and draws into its own figure;
    # capture it with gcf() rather than pre-creating one (a pre-created figure
    # would be left as an unclosed orphan because summary_plot ignores it).
    shap.summary_plot(
        pos, X_sample,
        plot_type='bar' if plot_type == 'bar' else 'dot',
        max_display=max_display,
        show=False,
    )
    fig = plt.gcf()
    fig.tight_layout()
    fig.savefig(out_path, dpi=120, bbox_inches='tight')
    plt.close(fig)
    return out_path
