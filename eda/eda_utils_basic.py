'''
EDA Utils

EDA utils written by myself and AI

Purpose:
* Frequently used functions for basic EDA
* How can I leverage AI to streamline and improve EDA process?
'''
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Distributions / value counts
# ---------------------------------------------------------------------------
def value_counts_top(df, col, top_k=20, dropna=False, normalize=False):
    '''Top-k value_counts as a tidy DataFrame.'''
    s = df[col].value_counts(dropna=dropna, normalize=normalize).head(top_k)
    metric = 'share' if normalize else 'count'
    return pd.DataFrame({col: s.index.tolist(), metric: s.values})


def plot_top_values(df, col, top_k=20, dropna=False, normalize=False,
                    ax=None, title=None, figsize=(8, 5)):
    '''Horizontal bar chart of the top-k values in a column.'''
    counts = df[col].value_counts(dropna=dropna, normalize=normalize).head(top_k)
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    counts.iloc[::-1].plot(kind='barh', ax=ax)
    ax.set_xlabel('share' if normalize else 'count')
    ax.set_ylabel(col)
    ax.set_title(title or f"Top {top_k} {col}")
    plt.tight_layout()
    return ax


def missing_summary(df, top_k=None):
    '''Per-column missing rate, sorted desc.'''
    miss = df.isna().mean().sort_values(ascending=False)
    out = pd.DataFrame({'column': miss.index.tolist(), 'na_share': miss.values})
    if top_k is not None:
        out = out.head(top_k)
    return out


def duplicates_summary(df, col, top_k=20):
    '''Show ids in `col` that appear more than once.'''
    counts = df[col].value_counts(dropna=False)
    dupes = counts[counts > 1]
    out = pd.DataFrame({col: dupes.index.tolist(), 'count': dupes.values})
    return out.head(top_k), int(dupes.sum()), int(len(dupes))


# ---------------------------------------------------------------------------
# Group-by breakdowns
# ---------------------------------------------------------------------------
def crosstab_pct(df, row, col, normalize='index', dropna=False):
    '''Crosstab of row x col, normalized as percentages.'''
    ct = pd.crosstab(df[row], df[col], dropna=dropna, normalize=normalize)
    return (ct * 100).round(1)


def group_counts(df, group_cols, top_k=20):
    '''size() over one or more grouping columns, sorted.'''
    if isinstance(group_cols, str):
        group_cols = [group_cols]
    out = (
        df.groupby(group_cols, dropna=False)
        .size()
        .rename('count')
        .reset_index()
        .sort_values('count', ascending=False)
        .head(top_k)
        .reset_index(drop=True)
    )
    return out


# ---------------------------------------------------------------------------
# Time-based plots
# ---------------------------------------------------------------------------
def to_month(series):
    '''Coerce a date-like series to Period('M') (NaT-tolerant).'''
    return pd.to_datetime(series, errors='coerce').dt.to_period('M')


def monthly_counts(df, date_col, group_col=None):
    '''Counts by month, optionally split by `group_col`.  Rows with un-parseable dates are dropped.'''
    months = to_month(df[date_col])
    if group_col is None:
        s = months.dropna().value_counts().sort_index()
        return pd.DataFrame({'month': [str(x) for x in s.index], 'count': s.values})
    tmp = pd.DataFrame({'month': months, group_col: df[group_col]}).dropna(subset=['month'])
    out = tmp.groupby(['month', group_col], dropna=False).size().unstack(fill_value=0)
    out.index = out.index.astype(str)
    return out


def plot_monthly(df, date_col, group_col=None, top_k_groups=8,
                 ax=None, figsize=(10, 5), title=None):
    '''Line plot of monthly counts.  If group_col is given, plot top-k groups.'''
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    if group_col is None:
        out = monthly_counts(df, date_col)
        ax.plot(out['month'], out['count'], marker='o')
    else:
        out = monthly_counts(df, date_col, group_col=group_col)
        keep = out.sum(axis=0).sort_values(ascending=False).head(top_k_groups).index
        out = out[keep]
        for g in out.columns:
            ax.plot(out.index, out[g], marker='o', label=str(g))
        ax.legend(loc='upper left', fontsize=8)
    ax.set_xlabel('month')
    ax.set_ylabel('count')
    ax.set_title(title or f"Monthly counts of {date_col}"
                 + (f" by {group_col}" if group_col else ""))
    for label in ax.get_xticklabels():
        label.set_rotation(60)
        label.set_ha('right')
    plt.tight_layout()
    return ax


def parse_hour(time_series):
    '''Extract integer hour 0..23 from "HH:MM" / "HH:MM:SS" strings.'''
    s = time_series.astype(str).str.extract(r'^(\d{1,2})')[0]
    h = pd.to_numeric(s, errors='coerce')
    return h.where((h >= 0) & (h <= 23))


def plot_hour_of_day(df, time_col, group_col=None, top_k_groups=6,
                     ax=None, figsize=(10, 4), title=None):
    '''Bar/line plot of incident counts by hour of day (0..23).'''
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    hour = parse_hour(df[time_col])
    if group_col is None:
        counts = hour.value_counts().reindex(range(24), fill_value=0).sort_index()
        ax.bar(counts.index, counts.values)
    else:
        tmp = pd.DataFrame({'hour': hour, group_col: df[group_col]}).dropna(subset=['hour'])
        keep = tmp[group_col].value_counts().head(top_k_groups).index
        tmp = tmp[tmp[group_col].isin(keep)]
        pivot = (tmp.groupby(['hour', group_col]).size()
                 .unstack(fill_value=0).reindex(range(24), fill_value=0))
        for g in pivot.columns:
            ax.plot(pivot.index, pivot[g], marker='o', label=str(g))
        ax.legend(loc='upper right', fontsize=8)
    ax.set_xlabel('hour of day')
    ax.set_ylabel('count')
    ax.set_xticks(range(0, 24, 2))
    ax.set_title(title or f"Counts by hour of day ({time_col})")
    plt.tight_layout()
    return ax


def night_day_split(df, time_col, night_hours=(20, 21, 22, 23, 0, 1, 2, 3, 4, 5)):
    '''Tag each row as 'night' or 'day' from a time column; return value_counts.'''
    hour = parse_hour(df[time_col])
    bucket = np.where(hour.isin(night_hours), 'night',
                      np.where(hour.notna(), 'day', 'unknown'))
    return pd.Series(bucket, name='time_bucket').value_counts(dropna=False)
