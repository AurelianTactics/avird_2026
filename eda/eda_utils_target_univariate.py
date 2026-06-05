'''
EDA utils - univariate analysis against a binary target column.

Three function groups:

1. Feature schema      -- ``DEFAULT_DROP_COLS``, ``TARGET_SOURCE_COLS``,
                          ``default_feature_columns``
2. Basic EDA by target -- ``value_counts_by_target``, ``describe_by_target``,
                          ``basic_eda_by_target`` (inline display, optional CSVs)
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
)
# NOTE: the *other* derived-target columns produced by ``add_all_targets``
# (every generated target except the active one) are intentionally NOT listed
# statically above. They are dropped dynamically by ``default_feature_columns``
# via ``_derived_target_columns``, which resolves the canonical names from
# ``eda_utils_targets.TARGET_COL_NAMES``. A hand-maintained list silently
# omitted the templated ``SV Speed >= {threshold}`` column, leaking it into the
# feature set / ranking / SHAP; deriving from upstream prevents that drift.


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


# Fallback derived-target names, used only if ``eda_utils_targets`` cannot be
# imported. Mirrors ``eda_utils_targets.TARGET_COL_NAMES``; the SV-speed target
# is templated, so it is matched by prefix rather than an exact name.
_FALLBACK_DERIVED_TARGET_NAMES = (
    'No Injury Reported',
    'Injury Reported',
    'Multi Class Injury',
    'Binary Airbag Deployed',
    'Binary Vehicle Towed',
    'Potential Non-Trivial Accident',
)
_SV_SPEED_TARGET_PREFIX = 'SV Speed >= '


def _derived_target_columns(df_columns):
    '''Names in ``df_columns`` that are derived-target columns from
    ``add_all_targets`` (so they can be dropped from any feature set).

    Reads the canonical names from ``eda_utils_targets.TARGET_COL_NAMES`` so
    the drop-set never drifts from upstream. The SV-speed target name is a
    template (``"SV Speed >= {threshold}"``); it is matched by prefix so any
    threshold the notebook passed to ``add_all_targets`` is caught.
    '''
    columns = list(df_columns)
    try:
        from eda_utils_targets import TARGET_COL_NAMES
        names = list(TARGET_COL_NAMES.values())
    except Exception:
        names = list(_FALLBACK_DERIVED_TARGET_NAMES)
        names.append(_SV_SPEED_TARGET_PREFIX + '{threshold}')

    derived = set()
    for name in names:
        if '{' in name:
            prefix = name.split('{', 1)[0]
            derived.update(c for c in columns if str(c).startswith(prefix))
        else:
            derived.add(name)
    return derived


def default_feature_columns(df, target_col, drop_cols=DEFAULT_DROP_COLS,
                            extra_drop=()):
    '''Return the list of eligible feature columns after applying drop-lists.

    Drops the static ``drop_cols`` (defaults to ``DEFAULT_DROP_COLS``), the
    target column itself, the source columns of ``target_col`` from
    ``TARGET_SOURCE_COLS`` (falls back to empty if the target is unknown),
    every *other* derived-target column produced by ``add_all_targets``
    (resolved dynamically via ``_derived_target_columns`` so the
    cross-target-leakage drop never drifts from upstream -- this is what keeps
    the templated ``SV Speed >= {threshold}`` column out of the feature set),
    and any ``extra_drop`` the caller passes in.

    Raises ``KeyError`` if ``target_col`` is not in ``df.columns``.
    '''
    if target_col not in df.columns:
        raise KeyError(
            f'target_col={target_col!r} is not a column of df '
            f'(have {len(df.columns)} columns)'
        )
    source_cols = TARGET_SOURCE_COLS.get(target_col, ())
    derived_targets = _derived_target_columns(df.columns)
    excluded = (set(drop_cols) | set(source_cols) | set(derived_targets)
                | {target_col} | set(extra_drop))
    return [c for c in df.columns if c not in excluded]


# ---------------------------------------------------------------------------
# Basic EDA by target
# ---------------------------------------------------------------------------
def value_counts_by_target(df, feature_col, target_col, dropna=False,
                           positive_label=1):
    '''Wide value counts of ``feature_col`` segmented by ``target_col``.

    One row per distinct feature value, columns in this order:

      * ``pos_rate`` -- ``P(target == positive_label | feature_value)``, i.e.
        of the rows with this feature value, the fraction in the positive
        class. This is the headline signal: it reads *across* the row and is
        directly comparable between feature values (unaffected by class
        imbalance, unlike the raw share columns).
      * ``share_within_target={t}`` -- one per target value ``t``: of all rows
        in target class ``t``, the fraction with this feature value. Sums to
        1.0 down each column. Comparing ``=0`` vs ``=1`` shows whether a value
        is over-/under-represented in the positive class.
      * ``count={t}`` -- raw row count per target value, kept last so the
        reader can judge how much sample backs each rate.

    Rows are sorted by total count across targets, descending (the
    ``value_counts()`` convention), so ``.head(n)`` shows the dominant feature
    values rather than the alphabetically-first ones.

    NaN feature values are kept by default (``dropna=False``) and appear as a
    ``NaN`` row in the index. Feature values absent for a given target get
    ``count == 0`` / ``share == 0`` (not NaN), so the table is gap-free.

    ``pos_rate`` is NaN when ``positive_label`` never appears in ``target_col``
    (the positive class is undefined).
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

    # Pivot to one column per target value. A feature value missing for a
    # target is a genuine zero count (not unknown), so fill before assembling.
    counts = (tab.pivot(index=feature_col, columns=target_col, values='count')
              .fillna(0).astype('int64'))
    shares = (tab.pivot(index=feature_col, columns=target_col,
                        values='share_within_target')
              .fillna(0.0))
    target_values = list(counts.columns)

    # pos_rate = positive-class count / row total, read across the row. With
    # ~9.5% positives the raw share columns are dwarfed by the negative class;
    # pos_rate normalizes that out so feature values compare directly.
    n_total = counts.sum(axis=1)
    out = pd.DataFrame(index=counts.index)
    if positive_label in counts.columns:
        out['pos_rate'] = counts[positive_label] / n_total.replace(0, np.nan)
    else:
        out['pos_rate'] = np.nan
    for t in target_values:
        out[f'share_within_target={t}'] = shares[t]
    for t in target_values:
        out[f'count={t}'] = counts[t]

    # Sort by total count across targets, descending -- the value_counts()
    # convention. Without this the pivot leaves rows in alphabetical order, so
    # head(top_n) would show the first N names instead of the dominant levels
    # (e.g. cut off 'Waymo' on a high-cardinality entity column). Stable sort
    # keeps ties in their (alphabetical) pivot order.
    order = n_total.sort_values(ascending=False, kind='stable').index
    out = out.loc[order]
    out.index.name = 'feature_value'  # set after .loc, which inherits order's name
    return out


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


def _display_side_by_side(named_tables, header=None):
    '''Render ``[(name, DataFrame), ...]`` horizontally in a notebook.

    Uses ``IPython.display`` when available so the tables sit next to each
    other instead of stacking vertically. Falls back to plain ``print`` (still
    stacked) when run outside a notebook, so callers never crash headless.
    '''
    try:
        from IPython.display import display, HTML
    except Exception:  # not in a notebook / IPython unavailable
        if header:
            print(f'=== {header} ===')
        for name, tbl in named_tables:
            print(f'-- {name} --')
            print(tbl)
        return

    parts = []
    if header:
        parts.append(f'<h4 style="margin:0.4em 0">{header}</h4>')
    parts.append('<div style="display:flex;gap:2.5em;align-items:flex-start;'
                 'flex-wrap:wrap">')
    for name, tbl in named_tables:
        parts.append(
            f'<div><div style="font-weight:600;margin-bottom:0.2em">{name}'
            f'</div>{tbl.to_html()}</div>'
        )
    parts.append('</div>')
    display(HTML(''.join(parts)))


def basic_eda_by_target(df, target_col, feature_cols, out_dir=None,
                        show=True, top_n=20):
    '''Per-feature value-counts + describe, displayed inline in the notebook.

    For every column in ``feature_cols`` this computes
    ``value_counts_by_target`` (wide) and ``describe_by_target`` and, when
    ``show`` is true, renders the two tables *side by side* under a feature
    header -- so basic EDA is readable directly in the notebook instead of
    being scattered across hundreds of CSV files.

    Artifacts are opt-in: pass ``out_dir`` to also write
    ``{feature}__value_counts.csv`` / ``{feature}__describe.csv`` (the parent
    directory is created on entry). Leave ``out_dir=None`` (the default) and
    nothing is written to disk.

    ``top_n`` caps the value-counts rows shown for high-cardinality features
    (the full table is still returned / written). Returns a dict
    ``{feature: {'value_counts': DataFrame, 'describe': DataFrame}}`` so the
    notebook can reuse any table without recomputing.
    '''
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    results = {}
    for feat in feature_cols:
        if feat not in df.columns:
            # Defensive: the notebook builds feature_cols from
            # default_feature_columns(df, ...), but if a caller passes a
            # column that isn't in df, skip rather than raise.
            continue

        vc = value_counts_by_target(df, feat, target_col)
        ds = describe_by_target(df, feat, target_col)
        results[feat] = {'value_counts': vc, 'describe': ds}

        if show:
            shown_vc = vc.head(top_n) if top_n is not None else vc
            _display_side_by_side(
                [('value counts', shown_vc), ('describe', ds)],
                header=f'{feat}  vs  {target_col}',
            )

        if out_dir is not None:
            stem = _safe_filename(feat)
            vc.to_csv(out_dir / f'{stem}__value_counts.csv')
            ds.to_csv(out_dir / f'{stem}__describe.csv')

    return results


# ---------------------------------------------------------------------------
# Univariate ranking helpers
# ---------------------------------------------------------------------------
# Sentinel for filling NaN in categorical features before label encoding.
_MISSING_SENTINEL = '__MISSING__'


def _is_numeric_dtype(series):
    return pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series)


def _coerce_numeric(series):
    '''Best-effort numeric coercion. Returns float Series with NaN for non-numeric cells.

    Datetime columns are coerced to their int64 nanoseconds-since-epoch value
    (NaT -> NaN) so temporal features are scored on the numeric track (a
    monotonic time trend that AUC / correlation handle) instead of being
    treated as near-unique categorical levels -- the latter inflates discrete
    mutual information.
    '''
    if pd.api.types.is_datetime64_any_dtype(series):
        as_float = series.astype('int64').astype(float)
        return as_float.where(series.notna(), np.nan)
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
        n_levels = len(np.unique(codes))
        if n_levels < 2:
            return (np.nan, n_used)
        # Near-unique categoricals (IDs, raw datetimes that slipped past the
        # drop-list) overfit discrete MI -- each level maps to ~one row, which
        # inflates the score and lets noise dominate the ranking. Treat them as
        # unreliable rather than emitting a misleading number.
        if n_levels > max(20, 0.5 * n_used):
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

    Booleans are scored as numeric (0/1). Datetime columns are scored as
    numeric on their ns-since-epoch representation (see ``_coerce_numeric``)
    rather than categorical -- treating timestamps as categorical levels makes
    them near-unique, which inflates discrete mutual information. Object /
    string / category dtypes are categorical.
    '''
    if pd.api.types.is_bool_dtype(series):
        return 'numeric'
    if pd.api.types.is_datetime64_any_dtype(series):
        return 'numeric'
    if pd.api.types.is_numeric_dtype(series):
        return 'numeric'
    return 'categorical'


def rank_features(df, target_col, feature_cols=None, verbose=False):
    '''Score every feature against ``target_col`` and return a tidy ranking.

    Returns a DataFrame with columns
    ``[feature, dtype, n_non_null, n_unique, auc, auc_direction, ks,
       mutual_info, chi2_p, correlation]``
    sorted by ``mutual_info`` descending. Metrics not applicable to a
    feature's dtype return NaN (numeric-only: AUC / KS / correlation;
    categorical-only: chi-square). Mutual information runs for both.

    Caveat on the default sort: ``mutual_info`` comes from two different
    estimators (continuous for numeric, discrete for categorical) and is not
    strictly comparable across dtypes -- discrete MI carries a positive bias
    that grows with cardinality. ``n_unique`` is reported alongside so the
    reader can spot high-cardinality inflation, and near-unique categoricals
    are dropped from MI entirely (see ``_score_mutual_info``). Cross-check the
    per-metric columns rather than reading the MI sort as ground truth.

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
        n_unique = int(series.nunique(dropna=True))
        row = {
            'feature': feat,
            'dtype': str(series.dtype),
            'n_non_null': n_non_null,
            'n_unique': n_unique,
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
        'feature', 'dtype', 'n_non_null', 'n_unique',
        'auc', 'auc_direction', 'ks', 'mutual_info', 'chi2_p', 'correlation',
    ])
    return out.sort_values('mutual_info', ascending=False,
                           na_position='last').reset_index(drop=True)

