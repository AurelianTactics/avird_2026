'''
EDA utils - two-way (pairwise) interactions against a binary target.

Two function groups:

1. Two-way heatmaps -- ``target_rate_pivot``, ``plot_target_rate_heatmap``,
                       ``pairwise_heatmaps_to_png``
2. Stub decision tree -- ``fit_stub_tree``, ``stub_tree_text``,
                         ``stub_tree_png``

"Two-way" means pairwise (feat_i x feat_j). Both function groups expect the
notebook to pass in the top-K features it cares about -- the utils do not
pick K themselves. The notebook drives K from the SHAP ranking produced in
the modeling section.

Convention: helpers that take an ``out_dir`` / ``out_path`` argument create
the parent directories themselves.
'''
from math import ceil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier, export_text, plot_tree

# Single source of truth shared with eda_utils_target_univariate: the
# missing-value sentinel and the Windows-safe filename helper live there, so
# importing them here avoids drift between two copies.
from eda_utils_target_univariate import (
    _MISSING_SENTINEL as _MISSING_LABEL,
    _safe_filename,
)

_OTHER_LABEL = '__OTHER__'


# ---------------------------------------------------------------------------
# Helpers shared by the heatmap pathway
# ---------------------------------------------------------------------------
def _bucketize_for_pivot(series, max_levels):
    '''Reduce a column to <= max_levels labels suitable for a heatmap axis.

    * Numeric series -> ``pd.qcut`` into ``max_levels`` quantile bins
      (``duplicates='drop'`` to tolerate ties). The bin labels are the
      pandas Interval objects so the heatmap axis stays sortable.
    * Categorical / object series -> keep top ``max_levels`` by frequency,
      bucket the rest as ``__OTHER__``. NaNs become ``__MISSING__``.

    Returns the bucketed Series. Constant numeric columns return as a
    single-level series (caller can skip the pair). A heavily-tied numeric
    whose ``qcut`` collapses to a single bin falls back to value bucketing so
    the axis still reflects the actual distinct values instead of a degenerate
    one-row heatmap.
    '''
    if pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
        x = pd.to_numeric(series, errors='coerce')
        if x.dropna().nunique() < 2:
            # zero-variance -> single bucket
            return x.astype('object').where(x.notna(), _MISSING_LABEL)
        try:
            binned = pd.qcut(x, q=max_levels, duplicates='drop')
        except ValueError:
            binned = None
        # qcut can silently collapse a heavily-tied numeric (most mass on one
        # value) to a single bin, rendering as a degenerate 1xN heatmap row.
        # Detect that and fall back to value bucketing on the raw values.
        if binned is None or binned.cat.categories.size < 2:
            return _value_bucketize(
                x.astype('object').where(x.notna(), _MISSING_LABEL), max_levels)
        # Replace NaN bin assignment with the MISSING label
        return binned.astype('object').where(x.notna(), _MISSING_LABEL)

    s = series.astype('object').where(series.notna(), _MISSING_LABEL)
    return _value_bucketize(s, max_levels)


def _value_bucketize(s, max_levels):
    '''Keep the top ``max_levels`` values of an object Series by frequency,
    bucketing the rest as ``__OTHER__``.'''
    counts = s.value_counts(dropna=False)
    keep = set(counts.head(max_levels).index)
    return s.where(s.isin(keep), _OTHER_LABEL)


def target_rate_pivot(df, feat_a, feat_b, target_col, max_levels=10):
    '''Mean(target) and count pivots over (feat_a, feat_b).

    Returns ``(rate_pivot, count_pivot)``. The rate pivot carries NaN in
    cells with zero observations. Both pivots are bucketed first via
    ``_bucketize_for_pivot``.
    '''
    if feat_a not in df.columns:
        raise KeyError(f'feat_a={feat_a!r} not in df')
    if feat_b not in df.columns:
        raise KeyError(f'feat_b={feat_b!r} not in df')
    if target_col not in df.columns:
        raise KeyError(f'target_col={target_col!r} not in df')

    a = _bucketize_for_pivot(df[feat_a], max_levels=max_levels)
    b = _bucketize_for_pivot(df[feat_b], max_levels=max_levels)
    y = df[target_col].astype(float)

    # Force string labels so pivot ordering is stable and the heatmap axes
    # render predictably (Interval objects sort lexicographically otherwise).
    a = a.astype(str)
    b = b.astype(str)

    tmp = pd.DataFrame({'a': a, 'b': b, 'y': y})
    count_pivot = tmp.pivot_table(index='a', columns='b', values='y',
                                  aggfunc='size', fill_value=0)
    rate_pivot = tmp.pivot_table(index='a', columns='b', values='y',
                                 aggfunc='mean')
    # Align shapes (pivot_table with size vs mean may differ on empty cells)
    rate_pivot = rate_pivot.reindex(index=count_pivot.index,
                                    columns=count_pivot.columns)
    return rate_pivot, count_pivot


def plot_target_rate_heatmap(df, feat_a, feat_b, target_col,
                             ax=None, annot='both', cmap='RdBu_r',
                             max_levels=10, min_cell_count=0):
    '''Render the (feat_a x feat_b) target-rate heatmap.

    ``annot='rate'`` shows the percentage per cell, ``'count'`` shows N,
    ``'both'`` shows ``"rate% (n=count)"``. Cells with count < ``min_cell_count``
    are blanked in both color and annotation so low-confidence cells don't
    dominate the eye. Returns the matplotlib ``Axes``.
    '''
    rate, count = target_rate_pivot(df, feat_a, feat_b, target_col,
                                    max_levels=max_levels)

    rate_masked = rate.copy()
    if min_cell_count > 0:
        rate_masked = rate_masked.where(count >= min_cell_count)

    if ax is None:
        fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(rate_masked.to_numpy(), cmap=cmap, vmin=0.0, vmax=1.0,
                   aspect='auto')
    ax.set_xticks(range(len(rate_masked.columns)))
    ax.set_xticklabels([str(c) for c in rate_masked.columns],
                       rotation=45, ha='right')
    ax.set_yticks(range(len(rate_masked.index)))
    ax.set_yticklabels([str(c) for c in rate_masked.index])
    ax.set_xlabel(feat_b)
    ax.set_ylabel(feat_a)
    ax.set_title(f'Target rate of {target_col!r}\n{feat_a} x {feat_b}')

    if annot != 'none':
        for i in range(rate_masked.shape[0]):
            for j in range(rate_masked.shape[1]):
                r = rate_masked.iat[i, j]
                n = count.iat[i, j]
                if np.isnan(r):
                    continue
                if annot == 'rate':
                    txt = f'{r * 100:.0f}%'
                elif annot == 'count':
                    txt = f'{int(n)}'
                else:
                    txt = f'{r * 100:.0f}% (n={int(n)})'
                ax.text(j, i, txt, ha='center', va='center',
                        fontsize=8, color='black')
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04,
                 label=f'P({target_col} = 1)')
    return ax


def pairwise_heatmaps_to_png(df, feature_cols, target_col, out_dir,
                             max_levels=10, min_cell_count=None,
                             figsize=(8, 6)):
    '''Save a target-rate heatmap PNG for every (i < j) pair in ``feature_cols``.

    ``min_cell_count`` gates the cell annotations + colors -- defaults to
    ``max(10, ceil(3 / positive_rate))`` so the bar scales with class
    imbalance (~32 for the injury target's 9.5% positive rate). Pairs where
    the maximum cell count is below ``min_cell_count`` are skipped entirely
    (no PNG written) and logged via ``print``. Returns the list of paths
    actually written.
    '''
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if min_cell_count is None:
        pos_rate = float(df[target_col].astype(float).mean())
        if pos_rate <= 0:
            min_cell_count = 10
        else:
            min_cell_count = max(10, ceil(3 / pos_rate))

    cols = [c for c in feature_cols if c in df.columns]
    paths = []
    skipped = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            a, b = cols[i], cols[j]
            try:
                _, count = target_rate_pivot(df, a, b, target_col,
                                             max_levels=max_levels)
            except Exception as exc:
                skipped.append((a, b, f'pivot error: {exc}'))
                continue
            if count.to_numpy().max() < min_cell_count:
                skipped.append((a, b, f'max cell count {int(count.to_numpy().max())} < {min_cell_count}'))
                continue

            fig, ax = plt.subplots(figsize=figsize)
            try:
                plot_target_rate_heatmap(df, a, b, target_col, ax=ax,
                                         max_levels=max_levels,
                                         min_cell_count=min_cell_count)
                stem = f'{_safe_filename(a)}__x__{_safe_filename(b)}.png'
                out_path = out_dir / stem
                fig.tight_layout()
                fig.savefig(out_path, dpi=120, bbox_inches='tight')
                paths.append(out_path)
            finally:
                plt.close(fig)

    if skipped:
        print(f'[pairwise_heatmaps_to_png] skipped {len(skipped)} pair(s) '
              f'below min_cell_count={min_cell_count}:')
        for a, b, why in skipped[:10]:
            print(f'  - {a!r} x {b!r}: {why}')
        if len(skipped) > 10:
            print(f'  ... and {len(skipped) - 10} more')

    return paths


# ---------------------------------------------------------------------------
# Stub decision tree (interaction discovery, NOT prediction)
# ---------------------------------------------------------------------------
def _encode_for_tree(df, feature_cols):
    '''Build an ``(X_array, encoded_feature_names)`` tuple usable by
    ``DecisionTreeClassifier``.

    Object / category columns get ``pd.Categorical.codes`` (with a
    ``__MISSING__`` sentinel level). Numeric columns get median-fill.
    Returns the column order used so callers can label the tree.
    '''
    X = pd.DataFrame(index=df.index)
    for col in feature_cols:
        s = df[col]
        if pd.api.types.is_bool_dtype(s):
            X[col] = s.astype(float)
        elif pd.api.types.is_numeric_dtype(s):
            x = pd.to_numeric(s, errors='coerce')
            if x.notna().any():
                X[col] = x.fillna(float(x.median()))
            else:
                X[col] = x.fillna(0.0)
        else:
            s_obj = s.astype('object').where(s.notna(), _MISSING_LABEL)
            X[col] = pd.Categorical(s_obj).codes.astype(np.int64)
    return X.to_numpy(), list(X.columns)


def fit_stub_tree(df, feature_cols, target_col,
                  max_depth=3, min_samples_leaf=20, random_state=0):
    '''Fit a tiny ``DecisionTreeClassifier`` for interaction discovery.

    Stub = not a model. The depth-3 limit + balanced class weight produce
    a tree small enough to read off as "which two-feature splits beat
    which" rather than as a prediction model. Returns
    ``(tree, encoded_feature_names)``; the encoded-names list is the
    column order ``X`` was built in so the caller can label the tree.
    '''
    if target_col not in df.columns:
        raise KeyError(f'target_col={target_col!r} not in df')
    X, encoded_names = _encode_for_tree(df, feature_cols)
    y = df[target_col].astype(int).to_numpy()
    tree = DecisionTreeClassifier(
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        class_weight='balanced',
        random_state=random_state,
    )
    tree.fit(X, y)
    return tree, encoded_names


def stub_tree_text(tree, feature_names):
    '''Return the printable text representation of a fitted tree.'''
    return export_text(tree, feature_names=list(feature_names))


def stub_tree_png(tree, feature_names, out_path,
                  class_names=('no_injury', 'injury'),
                  figsize=(14, 8)):
    '''Render the tree as a PNG via sklearn ``plot_tree`` (no graphviz dep).'''
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=figsize)
    try:
        plot_tree(tree, feature_names=list(feature_names),
                  class_names=list(class_names),
                  filled=True, rounded=True, ax=ax, fontsize=8)
        fig.tight_layout()
        fig.savefig(out_path, dpi=120, bbox_inches='tight')
    finally:
        plt.close(fig)
    return out_path
