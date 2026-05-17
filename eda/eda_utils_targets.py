'''
EDA utils - target column construction.

Each `make_*_target(df, ..., debug=False)` takes a DataFrame and returns a
new Series (the candidate target column).  `debug=True` prints the source
value counts and the resulting target counts so the mapping is easy to
verify on a fresh dataset.

`add_all_targets(df, ...)` appends every target as a new column.

Source schema note: the SGO dataset uses two different shapes for the
"air bags" and "vehicle towed" fields across schema versions:
  - older schema: separate `CP ...?` / `SV ...?` columns with simple
    Yes/No/Unknown values
  - newer schema: a single compound `Any ... ?` / `Was Any ... ?` column
    with strings like "Yes Subject Vehicle, No Crash Partner"
The binary target helpers consume both shapes by case-insensitive
substring matching on "yes".
'''
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Source column names + value sets
# ---------------------------------------------------------------------------
INJURY_COL = 'Highest Injury Severity Alleged'
CRASH_WITH_COL = 'Crash With'
SV_SPEED_COL = 'SV Precrash Speed (MPH)'

AIRBAG_COLS = (
    'Any Air Bags Deployed?',        # newer schema (compound values)
    'CP Any Air Bags Deployed?',     # older schema (simple Yes/No)
    'SV Any Air Bags Deployed?',     # older schema (simple Yes/No)
)
TOWED_COLS = (
    'Was Any Vehicle Towed?',        # newer schema (compound)
    'CP Was Vehicle Towed?',         # older schema (simple Yes/No)
    'SV Was Vehicle Towed?',         # older schema (simple Yes/No) -
                                     # included for completeness; drop via
                                     # the `cols` arg if not wanted.
)

# Injury severity buckets.  "No Injured Reported" (note the singular) is a
# data variant that appears in ~1.8% of rows and is treated as no injury.
NO_INJURY_VALUES = (
    'No Injuries Reported',
    'No Injured Reported',
    'Property Damage. No Injured Reported',
)
MINOR_VALUES = (
    'Minor',
    'Minor W/ Hospitalization',
    'Minor W/O Hospitalization',
)
MODERATE_VALUES = (
    'Moderate',
    'Moderate W/ Hospitalization',
    'Moderate W/O Hospitalization',
)
SERIOUS_VALUES = ('Serious',)
FATALITY_VALUES = ('Fatality',)
INJURY_VALUES = MINOR_VALUES + MODERATE_VALUES + SERIOUS_VALUES + FATALITY_VALUES

PEDESTRIAN_CRASH_VALUES = ('Non-Motorist: Pedestrian',)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _contains_yes(x):
    '''Case-insensitive substring match for "yes".  Catches both simple
    "Yes" cells and compound cells like
    "Yes Subject Vehicle, No Crash Partner".  "Not Applicable" / "No" /
    "Unknown" / NaN -> False.'''
    if pd.isna(x):
        return False
    return 'yes' in str(x).lower()


def _safe_col(df, col):
    '''Return df[col] or an all-NaN Series if the column is missing.'''
    if col in df.columns:
        return df[col]
    return pd.Series([np.nan] * len(df), index=df.index)


# ---------------------------------------------------------------------------
# 1. No injury reported
# ---------------------------------------------------------------------------
def make_no_injury_target(df, col=INJURY_COL, debug=False):
    '''1 if `col` reports no injury / property-damage-only, else 0.

    Maps these source values to 1 (see NO_INJURY_VALUES):
        'No Injuries Reported'
        'No Injured Reported'                       (typo variant)
        'Property Damage. No Injured Reported'
    Everything else (including 'Unknown' and NaN) maps to 0.
    '''
    s = _safe_col(df, col)
    target = s.isin(NO_INJURY_VALUES).astype(int)
    if debug:
        print(f'[no_injury] source col: {col!r}')
        print(f'[no_injury] mapped-to-1 values: {list(NO_INJURY_VALUES)}')
        print('[no_injury] source value counts:')
        print(s.value_counts(dropna=False))
        print('[no_injury] target value counts:')
        print(target.value_counts())
    return target


# ---------------------------------------------------------------------------
# 2. Injury reported (binary)
# ---------------------------------------------------------------------------
def make_injury_reported_target(df, col=INJURY_COL, debug=False):
    '''1 if `col` reports any injury severity, else 0.

    Maps Minor / Moderate / Serious / Fatality (and the W/ and W/O
    Hospitalization variants for Minor and Moderate) to 1.
    No-injury / Unknown / NaN map to 0.
    '''
    s = _safe_col(df, col)
    target = s.isin(INJURY_VALUES).astype(int)
    if debug:
        print(f'[injury_reported] source col: {col!r}')
        print(f'[injury_reported] mapped-to-1 values: {list(INJURY_VALUES)}')
        print('[injury_reported] source value counts:')
        print(s.value_counts(dropna=False))
        print('[injury_reported] target value counts:')
        print(target.value_counts())
    return target


# ---------------------------------------------------------------------------
# 3. Multi-class injury
# ---------------------------------------------------------------------------
def make_multi_class_injury_target(df, col=INJURY_COL, debug=False):
    '''Ordinal severity:
        0 = no injury / unknown / not in mapping / NaN
        1 = Minor (any hospitalization variant)
        2 = Moderate (any hospitalization variant)
        3 = Serious
        4 = Fatality
    '''
    s = _safe_col(df, col)
    target = pd.Series(0, index=df.index, dtype=int)
    target = target.mask(s.isin(MINOR_VALUES), 1)
    target = target.mask(s.isin(MODERATE_VALUES), 2)
    target = target.mask(s.isin(SERIOUS_VALUES), 3)
    target = target.mask(s.isin(FATALITY_VALUES), 4)
    if debug:
        print(f'[multi_injury] source col: {col!r}')
        print(f'[multi_injury] 1 = {list(MINOR_VALUES)}')
        print(f'[multi_injury] 2 = {list(MODERATE_VALUES)}')
        print(f'[multi_injury] 3 = {list(SERIOUS_VALUES)}')
        print(f'[multi_injury] 4 = {list(FATALITY_VALUES)}')
        print('[multi_injury] source value counts:')
        print(s.value_counts(dropna=False))
        print('[multi_injury] target value counts (sorted by class):')
        print(target.value_counts().sort_index())
    return target


# ---------------------------------------------------------------------------
# 4. Binary airbag deployed
# ---------------------------------------------------------------------------
def make_binary_airbag_target(df, cols=AIRBAG_COLS, debug=False):
    '''1 if any of `cols` contains the substring "yes" (case-insensitive),
    else 0.  Tolerates missing columns -- they're skipped silently, which
    makes this safe to call on either schema version.'''
    return _build_yes_union(df, cols=cols, label='airbag', debug=debug)


# ---------------------------------------------------------------------------
# 5. Binary vehicle towed
# ---------------------------------------------------------------------------
def make_binary_vehicle_towed_target(df, cols=TOWED_COLS, debug=False):
    '''1 if any of `cols` contains the substring "yes" (case-insensitive),
    else 0.  See AIRBAG_COLS / TOWED_COLS for which columns are checked.'''
    return _build_yes_union(df, cols=cols, label='towed', debug=debug)


def _build_yes_union(df, cols, label, debug=False):
    present = [c for c in cols if c in df.columns]
    if not present:
        target = pd.Series(0, index=df.index, dtype=int)
        if debug:
            print(f'[{label}] none of {list(cols)} present; target = 0 for all rows')
        return target

    flags = pd.DataFrame(
        {c: df[c].map(_contains_yes) for c in present},
        index=df.index,
    )
    target = flags.any(axis=1).astype(int)
    if debug:
        print(f'[{label}] source cols present: {present}')
        for c in present:
            print(f'\n[{label}] {c!r} raw value counts:')
            print(df[c].value_counts(dropna=False))
            print(f'[{label}]   -> "yes"-flagged rows: {int(flags[c].sum())}')
        print(f'\n[{label}] target value counts:')
        print(target.value_counts())
    return target


# ---------------------------------------------------------------------------
# 6. SV speed >= threshold
# ---------------------------------------------------------------------------
def make_sv_speed_target(df, col=SV_SPEED_COL, threshold=10, debug=False):
    '''1 if SV pre-crash speed >= `threshold` MPH, else 0.  NaN -> 0.'''
    s = pd.to_numeric(_safe_col(df, col), errors='coerce')
    target = (s >= threshold).fillna(False).astype(int)
    if debug:
        print(f'[sv_speed>={threshold}] source col: {col!r}')
        print(f'[sv_speed>={threshold}] rows with numeric value: '
              f'{int(s.notna().sum())}, NaN: {int(s.isna().sum())}')
        print(f'[sv_speed>={threshold}] speed describe:')
        print(s.describe())
        print(f'[sv_speed>={threshold}] target value counts:')
        print(target.value_counts())
    return target


# ---------------------------------------------------------------------------
# 7. Potential non-trivial accident
# ---------------------------------------------------------------------------
def make_non_trivial_accident_target(df, sv_speed_threshold=10, debug=False):
    '''1 if ANY of the following hold, else 0:
        - injury reported          (make_injury_reported_target)
        - airbag deployed          (make_binary_airbag_target)
        - vehicle towed            (make_binary_vehicle_towed_target)
        - SV speed >= threshold    (make_sv_speed_target)
        - Crash With == 'Non-Motorist: Pedestrian'

    Note: the spec said "targets 2 through 6 equal to 1".  Multi-class
    injury (target 3) is redundant inside an OR with binary injury
    (target 2), so it's omitted here -- any positive multi-class value
    already implies target 2 = 1.
    '''
    injury = make_injury_reported_target(df)
    airbag = make_binary_airbag_target(df)
    towed = make_binary_vehicle_towed_target(df)
    speed = make_sv_speed_target(df, threshold=sv_speed_threshold)
    crash_with = _safe_col(df, CRASH_WITH_COL)
    pedestrian = crash_with.isin(PEDESTRIAN_CRASH_VALUES).astype(int)

    stacked = pd.DataFrame({
        'injury_reported': injury,
        'binary_airbag': airbag,
        'binary_towed': towed,
        f'sv_speed_ge_{sv_speed_threshold}': speed,
        'pedestrian': pedestrian,
    })
    target = (stacked.sum(axis=1) > 0).astype(int)
    if debug:
        print('[non_trivial] component positive-rate breakdown:')
        print(stacked.sum().rename('positives'))
        print(f'[non_trivial] total rows: {len(df)}')
        print('[non_trivial] target value counts:')
        print(target.value_counts())
        # how many rows trigger via exactly one component (sanity check)
        print('[non_trivial] # components positive per row:')
        print(stacked.sum(axis=1).value_counts().sort_index())
    return target


# ---------------------------------------------------------------------------
# Master: attach every target to a frame
# ---------------------------------------------------------------------------
TARGET_COL_NAMES = {
    'no_injury': 'No Injury Reported',
    'injury_reported': 'Injury Reported',
    'multi_class_injury': 'Multi Class Injury',
    'binary_airbag': 'Binary Airbag Deployed',
    'binary_towed': 'Binary Vehicle Towed',
    'sv_speed': 'SV Speed >= {threshold}',          # formatted at write time
    'non_trivial': 'Potential Non-Trivial Accident',
}


def add_all_targets(df, sv_speed_threshold=10, debug=False, inplace=False):
    '''
    Append every candidate target to *df* and return the result.

    Output columns (names from TARGET_COL_NAMES):
        'No Injury Reported'              (0/1)
        'Injury Reported'                 (0/1)
        'Multi Class Injury'              (0-4)
        'Binary Airbag Deployed'          (0/1)
        'Binary Vehicle Towed'            (0/1)
        'SV Speed >= {threshold}'         (0/1)
        'Potential Non-Trivial Accident'  (0/1)
    '''
    target = df if inplace else df.copy()
    speed_col = TARGET_COL_NAMES['sv_speed'].format(threshold=sv_speed_threshold)

    target[TARGET_COL_NAMES['no_injury']] = make_no_injury_target(df, debug=debug)
    target[TARGET_COL_NAMES['injury_reported']] = make_injury_reported_target(df, debug=debug)
    target[TARGET_COL_NAMES['multi_class_injury']] = make_multi_class_injury_target(df, debug=debug)
    target[TARGET_COL_NAMES['binary_airbag']] = make_binary_airbag_target(df, debug=debug)
    target[TARGET_COL_NAMES['binary_towed']] = make_binary_vehicle_towed_target(df, debug=debug)
    target[speed_col] = make_sv_speed_target(df, threshold=sv_speed_threshold, debug=debug)
    target[TARGET_COL_NAMES['non_trivial']] = make_non_trivial_accident_target(
        df, sv_speed_threshold=sv_speed_threshold, debug=debug,
    )
    return target
