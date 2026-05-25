'''
EDA utils - univariate analysis against a binary target column.

Three function groups:

1. Feature schema      -- ``DEFAULT_DROP_COLS``, ``TARGET_SOURCE_COLS``,
                          ``default_feature_columns``
2. Basic EDA by target -- ``value_counts_by_target``, ``describe_by_target``,
                          ``basic_eda_to_csvs``
3. Univariate ranking  -- ``rank_features`` (+ ``_score_*`` helpers added in
                          a downstream pass)

All public functions take a pandas DataFrame plus a target column name and
return a tidy DataFrame the notebook can save without further shaping.

The feature-schema helpers are the single source of truth for "which columns
are eligible to score against the target." Free-text / ID / location columns
are dropped statically; the source columns *of the current target* are dropped
dynamically via ``TARGET_SOURCE_COLS`` so we never score a target against the
columns that define it (the obvious leakage trap).

Convention: helpers that take an ``out_dir`` / ``out_path`` argument create the
parent directories themselves (``Path(...).mkdir(parents=True, exist_ok=True)``).
The notebook does not pre-create the subfolder tree.
'''
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.feature_selection import mutual_info_classif
from sklearn.metrics import roc_auc_score


# ---------------------------------------------------------------------------
# Feature schema
# ---------------------------------------------------------------------------
# Static drop-list grouped by reason. Columns named here are excluded from
# the feature set regardless of which target the notebook is analyzing.
# Missing columns are tolerated silently (defensive against schema drift).
DEFAULT_DROP_COLS = (
    # Free-text / narrative -- not useful as tabular categorical features.
    'Narrative',
    'Narrative - Same Incident ID',
    'Narrative - CBI?',
    'Weather - Other Text',
    'Source - Other Text',

    # Address / location -- high cardinality, identifier-like.
    'Address',
    'City',
    'Zip Code',
    'Latitude',
    'Longitude',

    # Officer / contact -- PII, identifier-like.
    'Investigating Officer Name',
    'Investigating Officer Phone',
    'Investigating Officer Email',

    # Identifiers -- per-row uniqueness, no generalizable signal.
    'Report ID',
    'Report Version',
    'VIN',
    'VIN Decoded',
    'Serial Number',
    'Same Vehicle ID',
    'Same Incident ID',

    # Other derived target columns produced by ``add_all_targets``.
    # The target the notebook picks for *this* run stays in the frame and
    # is dropped via ``default_feature_columns(target_col=...)``; the other
    # six are dropped here to prevent cross-target leakage when the
    # SHAP / univariate rankings score features against the chosen target.
    'No Injury Reported',
    'Multi Class Injury',
    'Binary Airbag Deployed',
    'Binary Vehicle Towed',
    'Potential Non-Trivial Accident',
)


# Per-target source columns -- the upstream columns each generated target is
# computed from. ``default_feature_columns(target_col=...)`` always strips
# these so we never score a target against its own definition.
#
# Mirrors ``eda_utils_targets.INJURY_COL`` / ``AIRBAG_COLS`` / ``TOWED_COLS``
# / ``SV_SPEED_COL`` / ``CRASH_WITH_COL``. When targets gain or lose source
# columns upstream, update this dict and every feature-list call inherits
# the correct drop set.
TARGET_SOURCE_COLS = {
    'No Injury Reported': ('Highest Injury Severity Alleged',),
    'Injury Reported': ('Highest Injury Severity Alleged',),
    'Multi Class Injury': ('Highest Injury Severity Alleged',),
    'Binary Airbag Deployed': (
        'Any Air Bags Deployed?',
        'CP Any Air Bags Deployed?',
        'SV Any Air Bags Deployed?',
    ),
    'Binary Vehicle Towed': (
        'Was Any Vehicle Towed?',
        'CP Was Vehicle Towed?',
        'SV Was Vehicle Towed?',
    ),
    # ``add_all_targets`` formats the SV-speed column name with the actual
    # threshold (e.g., "SV Speed >= 15"); register both the unformatted key
    # and a couple of common thresholds for convenience.
    'SV Speed >= 10': ('SV Precrash Speed (MPH)',),
    'SV Speed >= 15': ('SV Precrash Speed (MPH)',),
    'SV Speed >= 20': ('SV Precrash Speed (MPH)',),
    'Potential Non-Trivial Accident': (
        'Highest Injury Severity Alleged',
        'Any Air Bags Deployed?',
        'CP Any Air Bags Deployed?',
        'SV Any Air Bags Deployed?',
        'Was Any Vehicle Towed?',
        'CP Was Vehicle Towed?',
        'SV Was Vehicle Towed?',
        'SV Precrash Speed (MPH)',
        'Crash With',
    ),
}


def default_feature_columns(df, target_col, drop_cols=DEFAULT_DROP_COLS,
                            extra_drop=()):
    '''Return the list of eligible feature columns after applying drop-lists.

    Drops the static ``drop_cols`` (defaults to ``DEFAULT_DROP_COLS``), the
    target column itself, the source columns of ``target_col`` from
    ``TARGET_SOURCE_COLS`` (falls back to empty if the target is unknown),
    and any ``extra_drop`` the caller passes in.

    Raises ``KeyError`` if ``target_col`` is not in ``df.columns``.
    '''
    if target_col not in df.columns:
        raise KeyError(
            f'target_col={target_col!r} is not a column of df '
            f'(have {len(df.columns)} columns)'
        )
    source_cols = TARGET_SOURCE_COLS.get(target_col, ())
    excluded = set(drop_cols) | set(source_cols) | {target_col} | set(extra_drop)
    return [c for c in df.columns if c not in excluded]


# ---------------------------------------------------------------------------
# Basic EDA by target
# ---------------------------------------------------------------------------
def value_counts_by_target(df, feature_col, target_col, dropna=False,
                           normalize=False):
    '''Long-form value counts of ``feature_col`` segmented by ``target_col``.

    Returns a DataFrame with columns
    ``[feature_value, target_value, count, share_within_target]`` so the
    reader can see positive-rate-per-feature-value at a glance. NaN feature
    values are kept by default (``dropna=False``) and shown as ``NaN`` in
    the ``feature_value`` column.
    '''
    if feature_col not in df.columns:
        raise KeyError(f'feature_col={feature_col!r} not in df')
    if target_col not in df.columns:
        raise KeyError(f'target_col={target_col!r} not in df')

    tab = (
        df.groupby([target_col, feature_col], dropna=dropna)
        .size()
        .rename('count')
        .reset_index()
    )
    # share within each target group (sums to 1.0 per target value)
    totals = tab.groupby(target_col)['count'].transform('sum')
    tab['share_within_target'] = tab['count'] / totals.replace(0, np.nan)

    out = tab.rename(columns={feature_col: 'feature_value',
                              target_col: 'target_value'})
    # Order columns deterministically.
    return out[['feature_value', 'target_value', 'count', 'share_within_target']]


def describe_by_target(df, feature_col, target_col):
    '''pandas ``describe()`` of ``feature_col`` segmented by ``target_col``.

    For numeric features the output is the usual count/mean/std/min/.../max
    matrix; for object features it falls back to count/unique/top/freq.
    Columns are one per distinct target value.
    '''
    if feature_col not in df.columns:
        raise KeyError(f'feature_col={feature_col!r} not in df')
    if target_col not in df.columns:
        raise KeyError(f'target_col={target_col!r} not in df')

    return df.groupby(target_col, dropna=False)[feature_col].describe().T


def _safe_filename(name):
    '''Make a column name safe to use as a filename stem.

    Replaces filesystem-unfriendly characters with ``__`` so e.g.
    ``"CP/SV Any Air Bags Deployed?"`` -> ``"CP__SV Any Air Bags Deployed_"``.
    '''
    bad = '/\\:*?"<>|'
    out = ''.join('__' if ch in bad else ch for ch in name)
    return out.rstrip(' .')  # avoid trailing-space/dot files on Windows


def basic_eda_to_csvs(df, target_col, feature_cols, out_dir):
    '''Orchestrator: write per-feature value-counts + describe CSVs.

    For every column in ``feature_cols`` writes two CSVs to ``out_dir``:
      * ``{feature}__value_counts.csv`` -- output of ``value_counts_by_target``
      * ``{feature}__describe.csv``     -- output of ``describe_by_target``

    Creates ``out_dir`` (and any missing parents) on entry. Returns the list
    of paths written, in the order they were written.
    '''
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = []
    for feat in feature_cols:
        if feat not in df.columns:
            # Defensive: the notebook builds feature_cols from
            # default_feature_columns(df, ...), but if a caller passes a
            # column that isn't in df, skip rather than raise.
            continue
        stem = _safe_filename(feat)
        vc_path = out_dir / f'{stem}__value_counts.csv'
        ds_path = out_dir / f'{stem}__describe.csv'

        vc = value_counts_by_target(df, feat, target_col)
        vc.to_csv(vc_path, index=False)
        paths.append(vc_path)

        ds = describe_by_target(df, feat, target_col)
        ds.to_csv(ds_path)
        paths.append(ds_path)
    return paths


# ---------------------------------------------------------------------------
# Univariate ranking helpers
# ---------------------------------------------------------------------------
# Sentinel for filling NaN in categorical features before label encoding.
_MISSING_SENTINEL = '__MISSING__'


def _is_numeric_dtype(series):
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _coerce_numeric(series):
    '''Best-effort numeric coercion. Returns float Series with NaN for non-numeric cells.'''
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    return pd.to_numeric(series, errors='coerce')


def _score_auc(series, target):
    '''Discrimination magnitude + direction for a numeric feature.

    Returns ``(auc_magnitude, auc_direction, n_used)`` where
    ``auc_magnitude = max(raw_auc, 1 - raw_auc)`` (always in [0.5, 1.0])
    and ``auc_direction = +1`` if higher feature values predict the positive
    class, ``-1`` if higher feature values predict the negative class.
    Splitting magnitude from direction lets callers sort by discrimination
    strength while keeping the sign recoverable.

    Returns ``(NaN, NaN, n_used)`` if the feature has fewer than 2 distinct
    non-NaN values or if the target has only one class in the non-NaN rows.
    '''
    x = _coerce_numeric(series)
    mask = x.notna() & target.notna()
    n_used = int(mask.sum())
    if n_used < 2:
        return (np.nan, np.nan, n_used)
    x = x[mask]
    y = target[mask].astype(int)
    if x.nunique() < 2 or y.nunique() < 2:
        return (np.nan, np.nan, n_used)
    raw_auc = roc_auc_score(y, x)
    direction = 1 if raw_auc >= 0.5 else -1
    magnitude = max(raw_auc, 1.0 - raw_auc)
    return (float(magnitude), int(direction), n_used)


def _score_ks(series, target):
    '''Two-sample KS statistic between positive- and negative-class distributions.

    Returns ``(ks_stat, n_used)``. NaN if either class has 0 samples after
    filtering NaN feature values.
    '''
    x = _coerce_numeric(series)
    mask = x.notna() & target.notna()
    n_used = int(mask.sum())
    if n_used < 2:
        return (np.nan, n_used)
    x = x[mask]
    y = target[mask].astype(int)
    pos = x[y == 1]
    neg = x[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return (np.nan, n_used)
    result = scipy_stats.ks_2samp(pos.to_numpy(), neg.to_numpy())
    return (float(result.statistic), n_used)


def _encode_categorical(series):
    '''Label-encode a categorical/object series, filling NaN with the sentinel.

    Returns ``(codes, n_used)`` where ``codes`` is an int array and ``n_used``
    is the number of rows (sentinel-filled rows count as used).
    '''
    s = series.astype('object').where(series.notna(), _MISSING_SENTINEL)
    codes = pd.Categorical(s).codes.astype(np.int64)
    return codes, int(len(codes))


def _score_mutual_info(series, target, discrete):
    '''Mutual information between a feature and the binary target.

    For numeric features (``discrete=False``) NaNs are filled with the column
    median so ``mutual_info_classif`` doesn't choke. For categorical features
    (``discrete=True``) NaNs are encoded as a ``__MISSING__`` level via
    ``_encode_categorical``.

    Returns ``(mi, n_used)``.
    '''
    mask = target.notna()
    n_used = int(mask.sum())
    if n_used < 2:
        return (np.nan, n_used)
    y = target[mask].astype(int).to_numpy()

    if discrete:
        codes, _ = _encode_categorical(series[mask])
        if len(np.unique(codes)) < 2:
            return (np.nan, n_used)
        X = codes.reshape(-1, 1)
        mi = mutual_info_classif(X, y, discrete_features=True, random_state=0)
    else:
        x = _coerce_numeric(series[mask])
        if x.notna().sum() == 0:
            return (np.nan, n_used)
        median = float(x.median())
        x = x.fillna(median).to_numpy().reshape(-1, 1)
        if np.unique(x).size < 2:
            return (np.nan, n_used)
        mi = mutual_info_classif(x, y, discrete_features=False, random_state=0)
    return (float(mi[0]), n_used)


def _score_chi2(series, target):
    '''Chi-square test of independence between a categorical feature and the target.

    Returns ``(p_value, chi2_stat, n_used)``. NaN feature values get the
    sentinel level. Skips features with fewer than 2 distinct non-NaN levels.
    '''
    mask = target.notna()
    n_used = int(mask.sum())
    if n_used < 2:
        return (np.nan, np.nan, n_used)
    s = series[mask].astype('object').where(series[mask].notna(), _MISSING_SENTINEL)
    y = target[mask].astype(int)
    if s.nunique(dropna=False) < 2:
        return (np.nan, np.nan, n_used)
    table = pd.crosstab(s, y)
    if table.shape[0] < 2 or table.shape[1] < 2:
        return (np.nan, np.nan, n_used)
    result = scipy_stats.chi2_contingency(table.to_numpy())
    return (float(result.pvalue), float(result.statistic), n_used)


def _score_correlation(series, target):
    '''Spearman rank correlation between a numeric feature and the binary target.

    The target is 0/1 so this is essentially a point-biserial-as-rank.
    Returns ``(rho, n_used)``. NaN if zero variance after NaN-drop.
    '''
    x = _coerce_numeric(series)
    mask = x.notna() & target.notna()
    n_used = int(mask.sum())
    if n_used < 2:
        return (np.nan, n_used)
    x = x[mask]
    y = target[mask].astype(int)
    if x.nunique() < 2 or y.nunique() < 2:
        return (np.nan, n_used)
    rho, _ = scipy_stats.spearmanr(x, y)
    if np.isnan(rho):
        return (np.nan, n_used)
    return (float(rho), n_used)


def _classify_dtype(series):
    '''Bucket a column into 'numeric' or 'categorical' for scoring dispatch.

    Booleans are scored as numeric (0/1). Object / string / category dtypes
    are categorical. Datetime columns are treated as categorical (their
    raw timestamp magnitude is rarely meaningful as an AUC ranking).
    '''
    if pd.api.types.is_bool_dtype(series):
        return 'numeric'
    if pd.api.types.is_numeric_dtype(series):
        return 'numeric'
    return 'categorical'


def rank_features(df, target_col, feature_cols=None, verbose=False):
    '''Score every feature against ``target_col`` and return a tidy ranking.

    Returns a DataFrame with columns
    ``[feature, dtype, n_non_null, auc, auc_direction, ks, mutual_info,
       chi2_p, correlation]``
    sorted by ``mutual_info`` descending. Metrics not applicable to a
    feature's dtype return NaN (numeric-only: AUC / KS / correlation;
    categorical-only: chi-square). Mutual information runs for both.

    NaN handling per metric:
      * AUC / KS / correlation: drop NaN feature rows before scoring.
      * Mutual information (numeric): NaN -> column median.
      * Mutual information (categorical) + chi-square: NaN -> ``__MISSING__``
        sentinel level.

    Binary numeric columns (0/1 dtype) are scored on the numeric track only.
    If you want chi-square on a binary 0/1 column, cast it to object first.

    Raises ``KeyError`` if ``target_col`` is not a column.
    '''
    if target_col not in df.columns:
        raise KeyError(f'target_col={target_col!r} not in df')
    if feature_cols is None:
        feature_cols = default_feature_columns(df, target_col)

    target = df[target_col]

    rows = []
    for feat in feature_cols:
        if feat not in df.columns:
            if verbose:
                print(f'[rank_features] skipping {feat!r}: not in df')
            continue
        series = df[feat]
        kind = _classify_dtype(series)
        n_non_null = int(series.notna().sum())
        row = {
            'feature': feat,
            'dtype': str(series.dtype),
            'n_non_null': n_non_null,
            'auc': np.nan,
            'auc_direction': np.nan,
            'ks': np.nan,
            'mutual_info': np.nan,
            'chi2_p': np.nan,
            'correlation': np.nan,
        }

        if kind == 'numeric':
            auc_mag, auc_dir, _ = _score_auc(series, target)
            ks_stat, _ = _score_ks(series, target)
            mi, _ = _score_mutual_info(series, target, discrete=False)
            rho, _ = _score_correlation(series, target)
            row['auc'] = auc_mag
            row['auc_direction'] = auc_dir
            row['ks'] = ks_stat
            row['mutual_info'] = mi
            row['correlation'] = rho
        else:
            mi, _ = _score_mutual_info(series, target, discrete=True)
            p, _, _ = _score_chi2(series, target)
            row['mutual_info'] = mi
            row['chi2_p'] = p

        if verbose:
            print(f'[rank_features] {feat!r} ({kind}, n={n_non_null}): '
                  f'auc={row["auc"]}, mi={row["mutual_info"]}, '
                  f'chi2_p={row["chi2_p"]}, rho={row["correlation"]}')
        rows.append(row)

    out = pd.DataFrame(rows, columns=[
        'feature', 'dtype', 'n_non_null',
        'auc', 'auc_direction', 'ks', 'mutual_info', 'chi2_p', 'correlation',
    ])
    return out.sort_values('mutual_info', ascending=False,
                           na_position='last').reset_index(drop=True)

