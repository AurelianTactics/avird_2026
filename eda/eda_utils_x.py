'''
EDA utils - extension file.

Two themes here:

1. Contact-area co-occurrence: per-incident pairings of SV vs CP contact
   areas (the existing `contact_area_compare` only counts each side
   independently).

2. Categorical consolidation: light, reusable helpers to clean up
   near-duplicate string values (Make, Model, Operating Entity,
   Investigating Agency, State or Local Permit, State, ...) plus utilities
   to produce a suggested mapping that an LLM (or human) can review and
   feed back in as an explicit override.
'''
import re
from collections import Counter
from itertools import product

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from eda_utils_sgo import (
    CONTACT_AREAS,
    canonical_token,
    contact_area_columns,
    is_yes,
)


# ===========================================================================
# 1. Contact-area pair co-occurrence
# ===========================================================================
def _row_contact_areas(df, prefix):
    '''For each row, return a list of areas flagged Y in the prefix columns.'''
    cols = [c for c in contact_area_columns(prefix) if c in df.columns]
    if not cols:
        return [[] for _ in range(len(df))]
    flags = pd.DataFrame(
        {c.split(' - ')[-1]: is_yes(df[c]).values for c in cols},
        index=df.index,
    )
    areas = flags.columns.tolist()
    arr = flags.values
    return [[areas[i] for i in np.where(row)[0]] for row in arr]


def contact_area_pairs(df, include_unknown=True, drop_no_pair=True):
    '''
    Per-incident (SV area, CP area) co-occurrence counts.

    Each row may have multiple SV areas and multiple CP areas flagged 'Y'.
    Every cartesian (sv_area, cp_area) pair from a single row is counted
    once.

    Returns a DataFrame with columns:
      sv_area, cp_area, count,
      pct_of_rows  - count / len(df)         (a row can hit multiple pairs)
      pct_of_pairs - count / total_pairs     (share of all pairs across rows)
    '''
    sv_lists = _row_contact_areas(df, 'SV')
    cp_lists = _row_contact_areas(df, 'CP')

    counter = Counter()
    for sv, cp in zip(sv_lists, cp_lists):
        if not include_unknown:
            sv = [a for a in sv if a != 'Unknown']
            cp = [a for a in cp if a != 'Unknown']
        if not sv or not cp:
            continue
        for pair in product(sv, cp):
            counter[pair] += 1

    if not counter:
        return pd.DataFrame(
            columns=['sv_area', 'cp_area', 'count', 'pct_of_rows', 'pct_of_pairs']
        )

    rows = [
        {'sv_area': a, 'cp_area': b, 'count': n}
        for (a, b), n in counter.items()
    ]
    out = pd.DataFrame(rows)
    n_rows = max(len(df), 1)
    n_pairs = int(out['count'].sum())
    out['pct_of_rows'] = (out['count'] / n_rows * 100).round(2)
    out['pct_of_pairs'] = (out['count'] / max(n_pairs, 1) * 100).round(2)
    out = out.sort_values('count', ascending=False).reset_index(drop=True)

    if drop_no_pair:
        return out
    sv_only = sum(1 for sv, cp in zip(sv_lists, cp_lists) if sv and not cp)
    cp_only = sum(1 for sv, cp in zip(sv_lists, cp_lists) if cp and not sv)
    neither = sum(1 for sv, cp in zip(sv_lists, cp_lists) if not sv and not cp)
    print(f'rows: {len(df)}  '
          f'sv_only={sv_only}  cp_only={cp_only}  neither={neither}  '
          f'total_pairs={n_pairs}')
    return out


def contact_area_pair_matrix(df, include_unknown=True, normalize=None):
    '''
    Matrix view of the same data: rows = SV area, cols = CP area.

    normalize:
      None      - raw counts
      'rows'    - share within each SV area row
      'cols'    - share within each CP area column
      'all'     - share of total pairs
    '''
    pairs = contact_area_pairs(df, include_unknown=include_unknown)
    if pairs.empty:
        return pd.DataFrame()

    areas = [a for a in CONTACT_AREAS if include_unknown or a != 'Unknown']
    mat = (
        pairs.pivot_table(
            index='sv_area', columns='cp_area', values='count',
            aggfunc='sum', fill_value=0,
        )
        .reindex(index=areas, columns=areas, fill_value=0)
    )

    if normalize == 'rows':
        return (mat.div(mat.sum(axis=1).replace(0, np.nan), axis=0) * 100).round(1)
    if normalize == 'cols':
        return (mat.div(mat.sum(axis=0).replace(0, np.nan), axis=1) * 100).round(1)
    if normalize == 'all':
        total = mat.values.sum() or 1
        return (mat / total * 100).round(1)
    return mat


def plot_contact_area_pair_heatmap(df, include_unknown=True, normalize=None,
                                   ax=None, figsize=(8, 6), title=None,
                                   cmap='Blues', annot=True):
    '''Heatmap of SV (rows) vs CP (cols) contact-area co-occurrence.'''
    mat = contact_area_pair_matrix(df, include_unknown=include_unknown,
                                   normalize=normalize)
    if mat.empty:
        return None
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(mat.values, cmap=cmap, aspect='auto')
    ax.set_xticks(range(len(mat.columns)))
    ax.set_xticklabels(mat.columns, rotation=45, ha='right')
    ax.set_yticks(range(len(mat.index)))
    ax.set_yticklabels(mat.index)
    ax.set_xlabel('CP contact area')
    ax.set_ylabel('SV contact area')
    suffix = f' ({normalize} %)' if normalize else ''
    ax.set_title(title or f'SV x CP contact-area pairs{suffix}')
    if annot:
        fmt = '{:.1f}' if normalize else '{:.0f}'
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                v = mat.values[i, j]
                if v:
                    ax.text(j, i, fmt.format(v), ha='center', va='center',
                            fontsize=8,
                            color='white' if v > mat.values.max() / 2 else 'black')
    plt.colorbar(im, ax=ax)
    plt.tight_layout()
    return ax


# ===========================================================================
# 2. Categorical consolidation helpers
# ===========================================================================
# Light text canonicalization specific to this dataset.  More aggressive than
# eda_utils_sgo.canonical_token: also strips trailing punctuation suffixes
# like ".", "Inc.", "LLC", and stray tab runs, and collapses whitespace.
_LEGAL_SUFFIXES = (
    'incorporated', 'inc', 'llc', 'l l c', 'corporation', 'corp', 'company',
    'co', 'ltd', 'limited', 'gmbh', 'ag', 'sa', 's a',
)
_TRAILING_PUNCT_RE = re.compile(r'[\s\.,;:!\?]+$')
_TAB_RUN_RE = re.compile(r'\t+')


def normalize_org_name(x):
    '''Lower, strip punct, drop trailing legal-entity suffixes. NaN-tolerant.'''
    s = canonical_token(x)
    if not s:
        return s
    # remove tab runs that the source CSVs sometimes embed
    s = _TAB_RUN_RE.sub(' ', s).strip()
    # strip trailing punctuation
    s = _TRAILING_PUNCT_RE.sub('', s)
    # drop one trailing legal suffix (e.g. "waymo llc" -> "waymo")
    parts = s.split()
    while parts and parts[-1] in _LEGAL_SUFFIXES:
        parts.pop()
    return ' '.join(parts) or None


# US state name <-> 2-letter code map (50 + DC).  Used by normalize_state.
_STATE_TO_CODE = {
    'alabama': 'AL', 'alaska': 'AK', 'arizona': 'AZ', 'arkansas': 'AR',
    'california': 'CA', 'colorado': 'CO', 'connecticut': 'CT',
    'delaware': 'DE', 'district of columbia': 'DC', 'florida': 'FL',
    'georgia': 'GA', 'hawaii': 'HI', 'idaho': 'ID', 'illinois': 'IL',
    'indiana': 'IN', 'iowa': 'IA', 'kansas': 'KS', 'kentucky': 'KY',
    'louisiana': 'LA', 'maine': 'ME', 'maryland': 'MD',
    'massachusetts': 'MA', 'michigan': 'MI', 'minnesota': 'MN',
    'mississippi': 'MS', 'missouri': 'MO', 'montana': 'MT',
    'nebraska': 'NE', 'nevada': 'NV', 'new hampshire': 'NH',
    'new jersey': 'NJ', 'new mexico': 'NM', 'new york': 'NY',
    'north carolina': 'NC', 'north dakota': 'ND', 'ohio': 'OH',
    'oklahoma': 'OK', 'oregon': 'OR', 'pennsylvania': 'PA',
    'rhode island': 'RI', 'south carolina': 'SC', 'south dakota': 'SD',
    'tennessee': 'TN', 'texas': 'TX', 'utah': 'UT', 'vermont': 'VT',
    'virginia': 'VA', 'washington': 'WA', 'west virginia': 'WV',
    'wisconsin': 'WI', 'wyoming': 'WY',
}
_VALID_CODES = set(_STATE_TO_CODE.values())


def normalize_state(x):
    '''Map full-name and 2-letter forms to a canonical 2-letter code.'''
    if pd.isna(x):
        return None
    s = str(x).strip()
    if not s:
        return None
    # also handles trailing whitespace from the source data ("CA " variants)
    upper = s.upper().strip()
    if upper in _VALID_CODES:
        return upper
    lower = s.lower().strip()
    return _STATE_TO_CODE.get(lower)


# ---------------------------------------------------------------------------
# Generic apply / suggest helpers
# ---------------------------------------------------------------------------
def apply_normalizer(series, normalizer):
    '''Run any (value -> value or None) callable across a Series.'''
    return series.map(normalizer)


def apply_mapping(series, mapping, default='self', normalizer=None):
    '''
    Apply an explicit consolidation mapping.

    mapping       : dict {raw_or_canonical_key: canonical_label}
    default       : 'self' keeps the original value when no key matches;
                    None replaces with NaN; any other value substitutes.
    normalizer    : optional callable applied to *both* the series values
                    and the mapping keys before lookup.  Use this to make
                    the mapping case/punct-insensitive, e.g.
                        apply_mapping(s, m, normalizer=normalize_org_name)
    '''
    if normalizer is None:
        norm_map = mapping
        def lookup(v):
            return mapping.get(v, v if default == 'self' else default)
    else:
        norm_map = {normalizer(k): v for k, v in mapping.items()}
        def lookup(v):
            key = normalizer(v)
            if key in norm_map:
                return norm_map[key]
            if default == 'self':
                return v
            return default
    return series.map(lookup)


def consolidation_diff(series, normalized):
    '''Side-by-side raw-vs-normalized counts for spot checking.'''
    raw = series.value_counts(dropna=False)
    norm = pd.Series(normalized).value_counts(dropna=False)
    return pd.DataFrame({
        'unique_before': [int(raw.size)],
        'unique_after': [int(norm.size)],
        'na_before': [int(series.isna().sum())],
        'na_after': [int(pd.Series(normalized).isna().sum())],
    })


def suggest_consolidation(series, score_cutoff=88, min_count=1,
                          normalizer=None, top_k=None):
    '''
    Use rapidfuzz to cluster near-duplicate values and propose a mapping.

    Returns a DataFrame with columns:
      canonical    - chosen group label (most common raw value in the group)
      member       - a raw value mapped into that group
      member_count - count of `member` in `series`
      score        - similarity of `member` vs `canonical` (100 = identical)

    Workflow:
      1. df_sugg = suggest_consolidation(df['Operating Entity'])
      2. eyeball it; build a `mapping = {member: canonical, ...}` dict
      3. df['Operating Entity Clean'] = apply_mapping(df['Operating Entity'], mapping)
    '''
    try:
        from rapidfuzz import fuzz, process
    except ImportError as e:
        raise ImportError(
            'suggest_consolidation requires rapidfuzz. Install with: '
            'uv pip install rapidfuzz'
        ) from e

    counts = series.value_counts(dropna=True)
    counts = counts[counts >= min_count]
    if top_k is not None:
        counts = counts.head(top_k)
    values = counts.index.astype(str).tolist()
    if normalizer is not None:
        norm_values = [normalizer(v) or v for v in values]
    else:
        norm_values = [v.strip().lower() for v in values]

    # Greedy clustering: walk values from most-frequent to least, attaching
    # each to an existing canonical if similarity is >= cutoff, else
    # promoting it to a new canonical.
    canonicals = []           # list of (canonical_norm, canonical_raw)
    assignments = []          # list of (member_raw, canonical_raw, score)
    for raw, norm in zip(values, norm_values):
        if not canonicals:
            canonicals.append((norm, raw))
            assignments.append((raw, raw, 100))
            continue
        match = process.extractOne(
            norm, [c[0] for c in canonicals],
            scorer=fuzz.token_set_ratio, score_cutoff=score_cutoff,
        )
        if match is None:
            canonicals.append((norm, raw))
            assignments.append((raw, raw, 100))
        else:
            _, score, idx = match
            assignments.append((raw, canonicals[idx][1], int(score)))

    out = pd.DataFrame(assignments, columns=['member', 'canonical', 'score'])
    out['member_count'] = out['member'].map(counts).astype(int)
    out = out[['canonical', 'member', 'member_count', 'score']]
    out = out.sort_values(
        ['canonical', 'member_count'], ascending=[True, False]
    ).reset_index(drop=True)
    return out


def mapping_from_suggestions(suggestions, only_changes=True):
    '''Convert a `suggest_consolidation` frame into a {member: canonical} dict.

    only_changes=True drops self-maps (member == canonical).'''
    pairs = zip(suggestions['member'], suggestions['canonical'])
    return {m: c for m, c in pairs if not (only_changes and m == c)}


# ---------------------------------------------------------------------------
# Combined fields (Make + Model)
# ---------------------------------------------------------------------------
def combine_columns(df, cols, sep=' | ', name=None, normalizer=None):
    '''Concatenate two or more columns into a single, normalized field.

    Missing values become "" (treated as no token).  If *all* parts are
    missing, the result is NaN.
    '''
    parts = []
    for c in cols:
        s = df[c].astype('object').where(df[c].notna(), '')
        if normalizer is not None:
            s = s.map(lambda v: normalizer(v) or '')
        parts.append(s.astype(str))
    combined = parts[0]
    for p in parts[1:]:
        combined = combined.str.cat(p, sep=sep)
    combined = combined.str.strip(sep + ' ')
    combined = combined.replace('', np.nan)
    if name:
        combined.name = name
    return combined
