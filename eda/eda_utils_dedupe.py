'''
EDA utils - duplicate-report consolidation.

The AVIRD feed contains multiple reports for the same physical incident:
different reporting entities may each file, and a single entity may refile
revised versions of an earlier report. ``dedupe_same_incident`` collapses
those into one canonical row per incident.

Grouping rules
--------------
1. Rows with a non-blank 'Same Incident ID' group by that value.
2. Rows with blank or null 'Same Incident ID' fall back to the composite
   key ('Reporting Entity', 'Incident Date', 'Incident Time (24:00)', 'VIN').
   If any fallback component is missing, the row is treated as standalone.

Per-group consolidation
-----------------------
- Reports sorted by 'Report Submission Date', 'Report Version', 'Report ID'
  descending so the most recent report is canonical.
- Each output column is filled with the most recent non-null value seen in
  the group (whitespace-only strings count as null).
- All unique narratives are concatenated into 'Narrative - Same Incident ID',
  latest first, separated by a configurable separator.

Usage
-----
    from eda_utils_dedupe import dedupe_same_incident
    df_clean = dedupe_same_incident(df, verbose=True)
'''
import numpy as np
import pandas as pd


_FALLBACK_KEY_COLS = (
    'Reporting Entity', 'Incident Date', 'Incident Time (24:00)', 'VIN',
)
_RECENCY_COLS = ('Report Submission Date', 'Report Version', 'Report ID')
_DEFAULT_NARRATIVE_SEP = '\n\n--- next report ---\n\n'


def _is_blank(v):
    '''True for None, NaN/NaT, and whitespace-only strings.'''
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() == ''
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _build_group_keys(df, sid_col, fallback_cols):
    '''Per-row group key, aligned with df.index ordering.

    Returns tuples so distinct branches (SID / FALLBACK / UNIQUE) can never
    collide with each other.
    '''
    fallback_present = [c for c in fallback_cols if c in df.columns]
    all_fallback_ok = len(fallback_present) == len(fallback_cols)
    has_sid = sid_col in df.columns
    out = []
    for i in range(len(df)):
        sid = df[sid_col].iat[i] if has_sid else None
        if not _is_blank(sid):
            out.append(('SID', str(sid).strip()))
            continue
        if not all_fallback_ok:
            out.append(('UNIQUE', df.index[i]))
            continue
        parts = [df[c].iat[i] for c in fallback_present]
        if any(_is_blank(p) for p in parts):
            out.append(('UNIQUE', df.index[i]))
        else:
            out.append(('FALLBACK', tuple(str(p).strip() for p in parts)))
    return out


def _join_unique(series, sep):
    '''Concat unique non-blank values in the order they appear in `series`.'''
    seen = []
    for v in series:
        if _is_blank(v):
            continue
        s = str(v).strip()
        if s and s not in seen:
            seen.append(s)
    return sep.join(seen) if seen else np.nan


def dedupe_same_incident(
    df,
    sid_col='Same Incident ID',
    fallback_cols=_FALLBACK_KEY_COLS,
    recency_cols=_RECENCY_COLS,
    narrative_col='Narrative',
    narrative_out='Narrative - Same Incident ID',
    narrative_sep=_DEFAULT_NARRATIVE_SEP,
    verbose=False,
):
    '''Collapse duplicate incident reports into one canonical row per incident.

    See module docstring for grouping and consolidation rules. Returns a new
    DataFrame; the input is not modified.
    '''
    n_in = len(df)
    work = df.copy()

    # 1. Sort recency desc (stable, so ties keep input order).
    rec_present = [c for c in recency_cols if c in work.columns]
    if rec_present:
        work = work.sort_values(
            rec_present, ascending=False,
            kind='mergesort', na_position='last',
        )

    # 2. Treat blank/whitespace strings as NaN so groupby.first() skips them.
    obj_cols = work.select_dtypes(include='object').columns
    if len(obj_cols):
        work[obj_cols] = work[obj_cols].replace(r'^\s*$', np.nan, regex=True)

    # 3. Build group key per row.
    work['__grp__'] = _build_group_keys(work, sid_col, fallback_cols)

    # 4. Canonical row = first non-null per column in recency order.
    canonical = (
        work.groupby('__grp__', sort=False)
            .first()
            .reset_index(drop=True)
    )

    # 5. Merged-narrative column (in the same group order as canonical).
    if narrative_col in work.columns:
        narratives = (
            work.groupby('__grp__', sort=False)[narrative_col]
                .apply(lambda s: _join_unique(s, narrative_sep))
        )
        canonical[narrative_out] = narratives.values

    if verbose:
        n_out = len(canonical)
        print(f'dedupe_same_incident: {n_in} -> {n_out} rows '
              f'({n_in - n_out} duplicates collapsed)')
    return canonical


def flag_incident_reports(
    df,
    sid_col='Same Incident ID',
    fallback_cols=_FALLBACK_KEY_COLS,
    recency_cols=_RECENCY_COLS,
    narrative_col='Narrative',
    narrative_out='Narrative - Same Incident ID',
    narrative_sep=_DEFAULT_NARRATIVE_SEP,
    flag_col='is_latest_of_multiple_report',
    multi_col='has_multiple_reports',
):
    '''Non-destructive sibling of ``dedupe_same_incident``.

    Returns a copy of *df* with the same rows (no drops, index preserved) plus:

    - ``is_latest_of_multiple_report``: True for the canonical row of each
      incident -- the most recent report of a multi-report group AND every
      standalone single-report incident (it IS the one row for that incident).
      The site filters this single boolean for one-row-per-incident.
    - ``has_multiple_reports``: True when the incident has >1 report.
    - ``Narrative - Same Incident ID``: the merged narrative (latest first,
      de-duplicated) attached to the canonical row only; NaN elsewhere.

    Uses the exact grouping (``_build_group_keys``) and recency ordering
    (``recency_cols`` desc) as ``dedupe_same_incident``, so filtering the
    output on ``flag_col`` reproduces that function's canonical rows.
    '''
    out = df.copy()

    # Per-row group key (SID / FALLBACK / UNIQUE), aligned to df.index.
    grp = pd.Series(_build_group_keys(df, sid_col, fallback_cols),
                    index=df.index)

    # has_multiple_reports: group size > 1.
    group_size = grp.map(grp.value_counts())
    out[multi_col] = (group_size > 1)

    # Canonical row = first row per group when sorted by recency desc (stable,
    # so ties keep input order -- matching dedupe_same_incident).
    rec_present = [c for c in recency_cols if c in df.columns]
    if rec_present:
        order = df.sort_values(
            rec_present, ascending=False,
            kind='mergesort', na_position='last',
        ).index
    else:
        order = df.index
    grp_in_order = grp.loc[order]
    canonical_idx = grp_in_order[~grp_in_order.duplicated(keep='first')].index

    flag = pd.Series(False, index=df.index)
    flag.loc[canonical_idx] = True
    out[flag_col] = flag

    # Merged narrative on the canonical row only (latest first).
    if narrative_col in df.columns:
        ordered = df.loc[order]
        joined = (
            ordered.groupby(grp.loc[order], sort=False)[narrative_col]
                   .apply(lambda s: _join_unique(s, narrative_sep))
        )
        narr = pd.Series(np.nan, index=df.index, dtype=object)
        canon_groups = grp.loc[canonical_idx]
        narr.loc[canonical_idx] = canon_groups.map(joined).values
        out[narrative_out] = narr

    return out
