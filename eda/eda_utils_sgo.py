'''
EDA utils related to SGO dataset
'''
import os
import re

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


YES_TOKENS = {'y', 'yes', 'true', '1', 't'}
NO_TOKENS = {'n', 'no', 'false', '0', 'f'}


def _norm(x):
    if pd.isna(x):
        return None
    return str(x).strip().lower()


def is_yes(series):
    '''Boolean Series for cells that read as "yes/Y/true/1".'''
    return series.map(_norm).isin(YES_TOKENS)


def has_value(series):
    '''Boolean Series for cells that contain anything truthy beyond NaN/empty.'''
    return series.map(_norm).fillna('').str.len() > 0


def load_and_concat_csvs(paths):
    dfs = [pd.read_csv(p) for p in paths]
    names = [os.path.basename(p) for p in paths]

    base_name, base_df = names[0], dfs[0]
    for name, df in zip(names[1:], dfs[1:]):
        base_cols = set(base_df.columns)
        cols = set(df.columns)

        only_in_base = sorted(base_cols - cols)
        only_in_other = sorted(cols - base_cols)
        if only_in_base:
            print(f"Only in {base_name}:")
            for c in only_in_base:
                print(f"  {c}")
        if only_in_other:
            print(f"Only in {name}:")
            for c in only_in_other:
                print(f"  {c}")

        for col in sorted(base_cols & cols):
            if base_df[col].dtype != df[col].dtype:
                print(
                    f"Dtype mismatch '{col}': "
                    f"{base_name}={base_df[col].dtype}, "
                    f"{name}={df[col].dtype}"
                )

    return pd.concat(dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# Contact-area helpers
# ---------------------------------------------------------------------------
CONTACT_AREAS = [
    'Rear Left', 'Left', 'Front Left', 'Rear', 'Top',
    'Front', 'Rear Right', 'Right', 'Front Right', 'Bottom', 'Unknown',
]


def contact_area_columns(prefix='SV'):
    return [f'{prefix} Contact Area - {a}' for a in CONTACT_AREAS]


def summarize_contact_areas(df, prefix='SV'):
    '''Counts of yes/y across all "<prefix> Contact Area - X" columns.'''
    cols = [c for c in contact_area_columns(prefix) if c in df.columns]
    if not cols:
        return pd.DataFrame(columns=['area', 'count'])
    counts = {c.split(' - ')[-1]: int(is_yes(df[c]).sum()) for c in cols}
    out = pd.DataFrame({'area': list(counts.keys()), 'count': list(counts.values())})
    return out.sort_values('count', ascending=False).reset_index(drop=True)


def contact_area_compare(df):
    '''Side-by-side counts for SV (subject vehicle) vs CP (contact party).'''
    sv = summarize_contact_areas(df, 'SV').rename(columns={'count': 'SV'})
    cp = summarize_contact_areas(df, 'CP').rename(columns={'count': 'CP'})
    out = sv.merge(cp, on='area', how='outer').fillna(0)
    out['SV'] = out['SV'].astype(int)
    out['CP'] = out['CP'].astype(int)
    return out.sort_values('SV', ascending=False).reset_index(drop=True)


def plot_contact_area_compare(df, ax=None, figsize=(9, 5), title=None):
    cmp = contact_area_compare(df).set_index('area')
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    cmp.plot(kind='bar', ax=ax)
    ax.set_ylabel('count')
    ax.set_title(title or 'Contact area: SV vs CP')
    plt.tight_layout()
    return ax


# ---------------------------------------------------------------------------
# Data availability summary
# ---------------------------------------------------------------------------
def data_availability_summary(df):
    '''Counts of yes-flagged "Data Availability - *" columns.'''
    cols = [c for c in df.columns if c.startswith('Data Availability - ')]
    counts = {c.replace('Data Availability - ', ''): int(is_yes(df[c]).sum())
              for c in cols}
    out = pd.DataFrame({'source': list(counts.keys()), 'count': list(counts.values())})
    out = out.sort_values('count', ascending=False).reset_index(drop=True)
    out['share'] = (out['count'] / max(len(df), 1)).round(3)
    return out


# ---------------------------------------------------------------------------
# Vehicle-stopped analysis
# ---------------------------------------------------------------------------
def vehicle_stopped_analysis(df, speed_col='SV Precrash Speed (MPH)',
                             group_col='Highest Injury Severity Alleged',
                             stopped_threshold=1.0):
    '''Split rows into stopped vs moving (by SV pre-crash speed) and breakdown.'''
    if speed_col not in df.columns:
        raise KeyError(f"{speed_col} not in dataframe")
    speed = pd.to_numeric(df[speed_col], errors='coerce')
    bucket = np.where(speed.isna(), 'unknown',
                      np.where(speed < stopped_threshold, 'stopped', 'moving'))
    bucket = pd.Series(bucket, index=df.index, name='sv_motion')
    overall = bucket.value_counts(dropna=False).rename('count').to_frame()
    overall['share'] = (overall['count'] / len(df)).round(3)
    if group_col and group_col in df.columns:
        ct = pd.crosstab(df[group_col], bucket, dropna=False)
        return overall, ct
    return overall, None


# ---------------------------------------------------------------------------
# Redacted / version-field analysis
# ---------------------------------------------------------------------------
REDACTED_PATTERNS = ('redacted', 'cbi', '[redacted]', 'confidential')


def is_redacted(series):
    '''True for cells whose text matches a redaction marker.'''
    s = series.map(_norm).fillna('')
    return s.apply(lambda v: any(p in v for p in REDACTED_PATTERNS))


def redacted_breakdown(df, value_cols, group_col='Reporting Entity', top_k=20):
    '''For each value_col, count redacted cells per group_col.'''
    rows = []
    for col in value_cols:
        if col not in df.columns:
            continue
        red = is_redacted(df[col])
        agg = (df.assign(_redacted=red)
               .groupby(group_col, dropna=False)['_redacted']
               .agg(['sum', 'count']))
        agg = agg.rename(columns={'sum': 'redacted', 'count': 'total'})
        agg['share'] = (agg['redacted'] / agg['total']).round(3)
        agg = agg.assign(column=col).reset_index()
        rows.append(agg[[group_col, 'column', 'redacted', 'total', 'share']])
    if not rows:
        return pd.DataFrame()
    out = pd.concat(rows, ignore_index=True)
    return out.sort_values('redacted', ascending=False).head(top_k).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Light text canonicalization
# ---------------------------------------------------------------------------
_PUNCT_RE = re.compile(r'[\s\-_,./]+')


def canonical_token(x):
    '''Lowercase, collapse whitespace/punct, strip.  None-tolerant.'''
    if pd.isna(x):
        return None
    s = str(x).strip().lower()
    s = _PUNCT_RE.sub(' ', s).strip()
    s = re.sub(r'\s+', ' ', s)
    return s or None


def consolidate_column(series, manual_map=None):
    '''
    Lightly normalize string values, then apply an optional manual map of
    canonical_token -> canonical_label to consolidate near-duplicates.
    Returns a new Series.
    '''
    canon = series.map(canonical_token)
    if manual_map:
        clean = {canonical_token(k): v for k, v in manual_map.items()}
        canon = canon.map(lambda x: clean.get(x, x))
    return canon


def value_counts_for_treatment(df, col, top_k=50):
    '''Pair raw vs canonical value counts side by side to spot duplicates.'''
    raw_s = df[col].value_counts(dropna=False).head(top_k)
    raw = pd.DataFrame({col: raw_s.index.tolist(), 'raw': raw_s.values})
    can_s = consolidate_column(df[col]).value_counts(dropna=False).head(top_k)
    can = pd.DataFrame({'canonical': can_s.index.tolist(),
                        'canonical_count': can_s.values})
    return raw, can


# ---------------------------------------------------------------------------
# Same-Incident-ID duplicate diagnostics
# ---------------------------------------------------------------------------
def same_incident_duplicates(df, col='Same Incident ID', top_k=20):
    '''Show ids that appear more than once and how often.'''
    s = df[col].dropna().astype(str)
    counts = s.value_counts()
    dupes = counts[counts > 1]
    summary = pd.DataFrame({
        'unique_ids': [int(len(counts))],
        'ids_with_dupes': [int(len(dupes))],
        'rows_in_dupes': [int(dupes.sum())],
    })
    head = pd.DataFrame({col: dupes.index.tolist(), 'count': dupes.values}).head(top_k)
    return summary, head
