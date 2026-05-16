'''
EDA utils - data treatment / cleaning helpers.

Split out from eda_utils_co_impact.py so the cleaning side of the codebase
lives in one place.  Two themes:

1. Categorical consolidation: light, reusable helpers to clean up
   near-duplicate string values (Make, Model, Operating Entity,
   Investigating Agency, State or Local Permit, State, ...) plus utilities
   to produce a suggested mapping that an LLM (or human) can review and
   feed back in as an explicit override.

2. Master-entity rollup: collapse Operating Entity + Reporting Entity into
   a single canonical display name (e.g. all Waymo variants -> "Waymo").

`apply_all_treatments(df)` runs every treatment in this module against a
copy of the input frame and appends cleaned columns alongside the
originals.
'''
import re

import numpy as np
import pandas as pd

from eda_utils_sgo import canonical_token


# ===========================================================================
# 1. Categorical consolidation helpers
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


# ===========================================================================
# 2. Master-entity rollup (Operating + Reporting -> one display name)
# ===========================================================================
# Matches dotted acronyms like "L.L.C.", "U.S.A.", "A.G." so we can collapse
# them to "LLC", "USA", "AG" before the legal-suffix strip runs.
_DOTTED_ACRONYM_RE = re.compile(r'\b(?:[A-Za-z]\.){2,}[A-Za-z]?')

# Short tokens we keep lowercased inside multi-word names so we don't end up
# with "Bank Of America" or "Cruise And Co".
_DISPLAY_KEEP_LOWER = {
    'and', 'or', 'the', 'of', 'a', 'an', 'in', 'on', 'at', 'by', 'to', 'for',
    'de', 'la', 'le', 'du', 'da', 'di', 'van', 'von',
}

# Legal-entity suffixes that the dataset uses on top of those handled by
# normalize_org_name (typos / less-common forms).
_EXTRA_LEGAL_SUFFIXES = ('lllc', 'pllc', 'llp', 'lp', 'plc', 'pty', 'kk')

# Trailing org-unit / region descriptors that aren't part of the brand.
# Sorted longest-first at module load so multi-word phrases win.
_DESCRIPTIVE_TRAILING = tuple(sorted({
    'research and development north america',
    'research and development na',
    'research and development',
    'north america',
    'autonomous driving',
    'rd na',
    'rd',
    'na',
    'ad',
}, key=len, reverse=True))


def _collapse_dotted_acronyms(s):
    if not isinstance(s, str):
        return s
    return _DOTTED_ACRONYM_RE.sub(lambda m: m.group(0).replace('.', ''), s)


def _strip_trailing_tokens(s, tokens):
    parts = s.split() if s else []
    while parts and parts[-1] in tokens:
        parts.pop()
    return ' '.join(parts)


def _strip_trailing_phrases(s, phrases):
    changed = True
    while changed and s:
        changed = False
        for phrase in phrases:
            if s == phrase:
                return ''
            if s.endswith(' ' + phrase):
                s = s[:-(len(phrase) + 1)].rstrip()
                changed = True
                break
    return s


def _normalize_org_for_master(x):
    '''normalize_org_name plus dotted-acronym collapse, descriptive-suffix and
    extra legal-suffix stripping so e.g.
        "Mercedes Benz Research and Development NA" -> "mercedes benz"
        "Motional AD"                               -> "motional"
        "Waymo LLLC"                                -> "waymo".
    '''
    if pd.isna(x):
        return None
    s = normalize_org_name(_collapse_dotted_acronyms(str(x)))
    if not s:
        return None
    # Iterate: strip descriptive phrases, then any newly exposed legal tokens,
    # until the tail stops changing.  Cheap because tails are short.
    while True:
        before = s
        s = _strip_trailing_tokens(s, _EXTRA_LEGAL_SUFFIXES)
        s = _strip_trailing_tokens(s, _LEGAL_SUFFIXES)
        s = _strip_trailing_phrases(s, _DESCRIPTIVE_TRAILING)
        if s == before:
            break
    return s or None


def _pretty_org_label(text):
    '''Turn a canonical token like "waymo" / "bmw" / "bank of america" into a
    display label: "Waymo", "BMW", "Bank of America".'''
    if not text:
        return None
    parts = text.split()
    out = []
    for i, p in enumerate(parts):
        if i > 0 and p in _DISPLAY_KEEP_LOWER:
            out.append(p)
        elif len(p) <= 3 and p.isalpha() and p not in _DISPLAY_KEEP_LOWER:
            out.append(p.upper())
        else:
            out.append(p.capitalize())
    return ' '.join(out)


def add_master_entity(df, operating_col='Operating Entity',
                      reporting_col='Reporting Entity',
                      out_col='master_entity', normalizer=None,
                      fuzzy=True, score_cutoff=88, inplace=False):
    '''
    Build a single canonical display-name column from two raw-entity columns.

    For each row, pick the operating-entity value if present, else the
    reporting-entity value. Normalize it (lowercase, strip punctuation, drop
    legal suffixes like LLC/Inc/Corp, collapse dotted acronyms), optionally
    fuzzy-cluster near-duplicate canonical keys across both columns, then
    render a clean display label.

    Examples (all collapse to 'Waymo'):
        'WayMo LLC', 'waymo', 'waymo l.l.c. inc'

    Args:
        df             source DataFrame.
        operating_col  primary entity column.
        reporting_col  fallback entity column when operating value is blank.
        out_col        name of the new column.
        normalizer     raw-value -> canonical-key callable; default handles
                       legal suffixes and dotted acronyms.
        fuzzy          cluster near-duplicate canonical keys via rapidfuzz.
        score_cutoff   similarity threshold (0-100) for fuzzy clustering.
        inplace        modify df in place; otherwise return a copy.
    '''
    if normalizer is None:
        normalizer = _normalize_org_for_master

    target = df if inplace else df.copy()
    n = len(target)

    if operating_col in target.columns:
        op_raw = target[operating_col]
    else:
        op_raw = pd.Series([np.nan] * n, index=target.index)
    if reporting_col in target.columns:
        rp_raw = target[reporting_col]
    else:
        rp_raw = pd.Series([np.nan] * n, index=target.index)

    def _first_non_blank(a, b):
        if pd.notna(a) and str(a).strip():
            return a
        if pd.notna(b) and str(b).strip():
            return b
        return None

    chosen_raw = pd.Series(
        [_first_non_blank(a, b) for a, b in zip(op_raw, rp_raw)],
        index=target.index,
    )
    chosen_norm = chosen_raw.map(normalizer)

    if fuzzy:
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            process = None
        if process is not None:
            pool = pd.concat([op_raw.map(normalizer),
                              rp_raw.map(normalizer),
                              chosen_norm])
            counts = pool.dropna().value_counts()
            canonicals = []
            collapse = {}
            for norm in counts.index:
                if not canonicals:
                    canonicals.append(norm)
                    collapse[norm] = norm
                    continue
                m = process.extractOne(
                    norm, canonicals,
                    scorer=fuzz.token_set_ratio,
                    score_cutoff=score_cutoff,
                )
                if m is None:
                    canonicals.append(norm)
                    collapse[norm] = norm
                else:
                    collapse[norm] = m[0]
            chosen_norm = chosen_norm.map(
                lambda v: collapse.get(v) if pd.notna(v) else None
            )

    target[out_col] = chosen_norm.map(_pretty_org_label)
    return target


# ===========================================================================
# 3. Master: apply every treatment to a DataFrame
# ===========================================================================
# Columns the master function knows how to clean.  Edit these tuples when the
# source schema grows new entity-like or state-like fields.
_ORG_LIKE_COLUMNS = (
    'Operating Entity',
    'Reporting Entity',
    'Investigating Agency',
    'State or Local Permit',
    'Make',
    'Model',
)
_STATE_LIKE_COLUMNS = ('State',)


def apply_all_treatments(df, suffix=' Clean', inplace=False,
                         master_entity_col='master_entity',
                         make_model_col='Make Model',
                         fuzzy_master=True, score_cutoff=88):
    '''
    Run every treatment in this module against *df* and return a frame with
    cleaned columns appended alongside the originals.

    Adds, when the source column is present:
      'Operating Entity'        -> 'Operating Entity Clean'        (normalize_org_name)
      'Reporting Entity'        -> 'Reporting Entity Clean'
      'Investigating Agency'    -> 'Investigating Agency Clean'
      'State or Local Permit'   -> 'State or Local Permit Clean'
      'Make'                    -> 'Make Clean'
      'Model'                   -> 'Model Clean'
      'State'                   -> 'State Clean'                   (normalize_state)
    Plus, regardless of any individual source column:
      master_entity_col   from Operating + Reporting (add_master_entity)
      make_model_col      from Make + Model         (combine_columns)

    Args:
        df                  source DataFrame.
        suffix              appended to each cleaned column name.
        inplace             write into df; otherwise operate on a copy.
        master_entity_col   output column name for the master-entity rollup;
                            pass None to skip.
        make_model_col      output column name for the Make+Model combo;
                            pass None to skip.
        fuzzy_master        forwarded to add_master_entity.
        score_cutoff        forwarded to add_master_entity.

    Missing source columns are silently skipped, so this is safe to call on
    any subset of the dataset.
    '''
    target = df if inplace else df.copy()

    for col in _ORG_LIKE_COLUMNS:
        if col in target.columns:
            target[f'{col}{suffix}'] = target[col].map(normalize_org_name)

    for col in _STATE_LIKE_COLUMNS:
        if col in target.columns:
            target[f'{col}{suffix}'] = target[col].map(normalize_state)

    if master_entity_col and (
        'Operating Entity' in target.columns
        or 'Reporting Entity' in target.columns
    ):
        add_master_entity(
            target, out_col=master_entity_col,
            fuzzy=fuzzy_master, score_cutoff=score_cutoff, inplace=True,
        )

    if (
        make_model_col
        and 'Make' in target.columns
        and 'Model' in target.columns
    ):
        target[make_model_col] = combine_columns(
            target, ['Make', 'Model'], normalizer=normalize_org_name,
        )

    return target
