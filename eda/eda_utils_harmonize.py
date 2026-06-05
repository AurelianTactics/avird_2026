'''EDA utils - cross-schema-version analogue harmonization.

The two SGO schema versions encode several of the same real-world facts with
different column names, formats, or shapes. This module maps the early- and
later-schema analogue fields into a small set of common ``*_clean`` columns,
extending the cross-version union pattern already used for airbag/towed in
``eda_utils_targets`` (``_contains_yes`` / ``AIRBAG_COLS``).

Raw source columns are left intact; every harmonized column is *additive*. Each
helper tolerates a frame that is missing any given source column (via
``_safe_col``), so it is safe to call on either schema version alone or on the
combined superset frame.

Families:
  engagement  -> automation_engaged_clean, automation_system_type
  belted      -> passengers_belted_clean
  weather     -> weather_*_clean boolean flags (shared vocabulary)
  roadway     -> roadway_*_clean boolean condition flags
  lighting    -> lighting_clean (early-schema only; NULL on later rows)

Two semantic caveats are surfaced for the cleaning manifest:
  ENGAGEMENT_CAVEAT, LIGHTING_CAVEAT.
'''
import pandas as pd

from eda_utils_sgo import is_yes
from eda_utils_targets import _safe_col


ENGAGEMENT_CAVEAT = (
    "Semantic mismatch across versions: the early schema's 'Automation System "
    "Engaged?' encodes which system was involved (ADS/ADAS), while the later "
    "schema's 'Engagement Status' encodes the engagement state (Verified "
    "Engaged / Not Engaged). automation_engaged_clean folds both into an "
    "engagement state and is additive -- the raw columns are retained."
)
LIGHTING_CAVEAT = (
    "Lighting is present only in the early schema; later-schema rows have no "
    "source column and receive NULL for lighting_clean."
)


def _norm_str(x):
    '''Trimmed string, or None for NaN/blank.'''
    if pd.isna(x):
        return None
    s = str(x).strip()
    return s or None


def _eq(series, value):
    '''Case-insensitive equality of a (possibly missing) text column.'''
    target = value.lower()
    return series.map(lambda v: (_norm_str(v) or '').lower() == target)


# ---------------------------------------------------------------------------
# Engagement
# ---------------------------------------------------------------------------
def _engaged_from_status(v):
    s = _norm_str(v)
    if not s:
        return None
    low = s.lower()
    if 'not engaged' in low:
        return 'Not Engaged'
    if 'engaged' in low:          # Verified Engaged / Alleged Engaged
        return 'Engaged'
    return 'Unknown'              # Unknown - see Narrative


def _engaged_from_auto(v):
    s = _norm_str(v)
    if not s:
        return None
    if s.upper() in ('ADS', 'ADAS'):
        return 'Engaged'
    return 'Unknown'              # Unknown, see Narrative


def _system_type(v):
    s = _norm_str(v)
    if not s:
        return None
    u = s.upper()
    if u == 'ADS':
        return 'ADS'
    if u == 'ADAS':
        return 'ADAS'
    return 'Unknown'


def harmonize_engagement(df):
    '''Add automation_engaged_clean {Engaged, Not Engaged, Unknown} and
    automation_system_type {ADS, ADAS, Unknown}.

    Prefer the later schema's 'Engagement Status' for engagement state; fall
    back to the early schema's 'Automation System Engaged?'. System type comes
    from 'Automation System Engaged?' on either version (later is all "ADS").'''
    status = _safe_col(df, 'Engagement Status').map(_engaged_from_status)
    auto = _safe_col(df, 'Automation System Engaged?')
    engaged = status.combine_first(auto.map(_engaged_from_auto)).fillna('Unknown')
    system_type = auto.map(_system_type).fillna('Unknown')
    return df.assign(
        automation_engaged_clean=engaged,
        automation_system_type=system_type,
    )


# ---------------------------------------------------------------------------
# Belted
# ---------------------------------------------------------------------------
def _belted(v):
    s = _norm_str(v)
    if not s:
        return None
    low = s.lower()
    if low == 'yes' or 'all belted' in low:
        return 'All Belted'
    if 'no passenger' in low:                 # "No Passenger(s) [In|in] Vehicle"
        return 'No Passengers'
    if 'not belted' in low or low.startswith('no'):  # "No, see Narrative"
        return 'Not Belted'
    if 'unknown' in low:
        return 'Unknown'
    return 'Unknown'


def harmonize_belted(df):
    '''Add passengers_belted_clean {All Belted, No Passengers, Not Belted,
    Unknown}. Combines early 'SV Were All Passengers Belted?' and later
    'Were All Passengers Belted?'.'''
    early = _safe_col(df, 'SV Were All Passengers Belted?').map(_belted)
    later = _safe_col(df, 'Were All Passengers Belted?').map(_belted)
    return df.assign(passengers_belted_clean=early.combine_first(later))


# ---------------------------------------------------------------------------
# Weather (boolean flags with a shared vocabulary)
# ---------------------------------------------------------------------------
def harmonize_weather(df):
    '''Add weather_*_clean boolean flags. Cross-version pairs are OR-ed onto a
    shared vocabulary; later-only categories are carried as their own flags.'''
    def flag(col):
        return is_yes(_safe_col(df, col))

    return df.assign(
        weather_clear_clean=flag('Weather - Clear'),
        weather_snow_clean=flag('Weather - Snow'),
        # Partly Cloudy (later-only) folds into Cloudy.
        weather_cloudy_clean=flag('Weather - Cloudy') | flag('Weather - Partly Cloudy'),
        # early 'Fog/Smoke' <-> later 'Fog/Smoke/Haze'.
        weather_fog_smoke_clean=flag('Weather - Fog/Smoke') | flag('Weather - Fog/Smoke/Haze'),
        weather_rain_clean=flag('Weather - Rain'),
        weather_severe_wind_clean=flag('Weather - Severe Wind'),
        # early 'Unknown' <-> later 'Unk - See Narrative'.
        weather_unknown_clean=flag('Weather - Unknown') | flag('Weather - Unk - See Narrative'),
        # later-only categories, present-only-in-later.
        weather_dust_storm_clean=flag('Weather - Dust Storm'),
        weather_severe_hurricane_clean=flag('Weather - Severe Hurricane'),
        weather_structure_indoor_clean=flag('Weather - Structure-Indoor'),
    )


# ---------------------------------------------------------------------------
# Roadway (boolean condition flags)
# ---------------------------------------------------------------------------
def harmonize_roadway(df):
    '''Add roadway_*_clean boolean condition flags. Early text columns
    ('Roadway Surface' / 'Roadway Description') are matched against the later
    schema's 'Roadway-*' boolean flags where they correspond. 'Roadway Type'
    is shared and kept as-is (no harmonized column).'''
    surface = _safe_col(df, 'Roadway Surface')
    desc = _safe_col(df, 'Roadway Description')
    return df.assign(
        roadway_wet_surface_clean=(
            _eq(surface, 'Wet') | is_yes(_safe_col(df, 'Roadway-Wet Surface Condition'))
        ),
        roadway_work_zone_clean=(
            _eq(desc, 'Work Zone') | is_yes(_safe_col(df, 'Roadway-Work Zone'))
        ),
        roadway_degraded_marking_clean=(
            _eq(desc, 'Missing / Degraded Markings')
            | is_yes(_safe_col(df, 'Roadway-Missing/Degraded Marking'))
        ),
        roadway_traffic_incident_clean=(
            _eq(desc, 'Traffic Incident') | is_yes(_safe_col(df, 'Roadway-Traffic Incident'))
        ),
    )


# ---------------------------------------------------------------------------
# Lighting (early-schema only)
# ---------------------------------------------------------------------------
_LIGHTING_MAP = {
    'daylight': 'Daylight',
    'dark - lighted': 'Dark - Lighted',
    'dawn / dusk': 'Dawn/Dusk',
    'dawn/dusk': 'Dawn/Dusk',
    'dark - not lighted': 'Dark - Not Lighted',
    'unknown': 'Unknown',
    'dark - unknown lighting': 'Dark - Unknown',
    'other, see narrative': 'Other',
}


def _lighting(v):
    s = _norm_str(v)
    if not s:
        return None
    return _LIGHTING_MAP.get(s.lower(), 'Other')


def harmonize_lighting(df):
    '''Add lighting_clean from the early-only 'Lighting' column. Later-schema
    rows (no source column) get NULL (see LIGHTING_CAVEAT).'''
    return df.assign(lighting_clean=_safe_col(df, 'Lighting').map(_lighting))


# ---------------------------------------------------------------------------
# Orchestration + provenance metadata (consumed by the manifest, U7)
# ---------------------------------------------------------------------------
def harmonize_all(df):
    '''Apply every harmonization family. Additive; raw columns untouched.'''
    out = harmonize_engagement(df)
    out = harmonize_belted(out)
    out = harmonize_weather(out)
    out = harmonize_roadway(out)
    out = harmonize_lighting(out)
    return out


# col -> {derived_from: [source cols], description, caveat?}. Used by the
# column dictionary so harmonization provenance stays defined next to the code.
HARMONIZED_PROVENANCE = {
    'automation_engaged_clean': {
        'derived_from': ['Engagement Status', 'Automation System Engaged?'],
        'description': 'Engagement state {Engaged, Not Engaged, Unknown}.',
        'caveat': ENGAGEMENT_CAVEAT,
    },
    'automation_system_type': {
        'derived_from': ['Automation System Engaged?'],
        'description': 'Automation system type {ADS, ADAS, Unknown}.',
    },
    'passengers_belted_clean': {
        'derived_from': ['SV Were All Passengers Belted?', 'Were All Passengers Belted?'],
        'description': 'Belt status {All Belted, No Passengers, Not Belted, Unknown}.',
    },
    'weather_clear_clean': {'derived_from': ['Weather - Clear'], 'description': 'Clear weather flag.'},
    'weather_snow_clean': {'derived_from': ['Weather - Snow'], 'description': 'Snow weather flag.'},
    'weather_cloudy_clean': {'derived_from': ['Weather - Cloudy', 'Weather - Partly Cloudy'], 'description': 'Cloudy (incl. Partly Cloudy) flag.'},
    'weather_fog_smoke_clean': {'derived_from': ['Weather - Fog/Smoke', 'Weather - Fog/Smoke/Haze'], 'description': 'Fog/Smoke(/Haze) flag.'},
    'weather_rain_clean': {'derived_from': ['Weather - Rain'], 'description': 'Rain weather flag.'},
    'weather_severe_wind_clean': {'derived_from': ['Weather - Severe Wind'], 'description': 'Severe wind flag.'},
    'weather_unknown_clean': {'derived_from': ['Weather - Unknown', 'Weather - Unk - See Narrative'], 'description': 'Unknown weather flag.'},
    'weather_dust_storm_clean': {'derived_from': ['Weather - Dust Storm'], 'description': 'Dust storm flag (later-only).'},
    'weather_severe_hurricane_clean': {'derived_from': ['Weather - Severe Hurricane'], 'description': 'Severe hurricane flag (later-only).'},
    'weather_structure_indoor_clean': {'derived_from': ['Weather - Structure-Indoor'], 'description': 'Structure/indoor flag (later-only).'},
    'roadway_wet_surface_clean': {'derived_from': ['Roadway Surface', 'Roadway-Wet Surface Condition'], 'description': 'Wet surface condition flag.'},
    'roadway_work_zone_clean': {'derived_from': ['Roadway Description', 'Roadway-Work Zone'], 'description': 'Work zone flag.'},
    'roadway_degraded_marking_clean': {'derived_from': ['Roadway Description', 'Roadway-Missing/Degraded Marking'], 'description': 'Missing/degraded marking flag.'},
    'roadway_traffic_incident_clean': {'derived_from': ['Roadway Description', 'Roadway-Traffic Incident'], 'description': 'Traffic incident flag.'},
    'lighting_clean': {
        'derived_from': ['Lighting'],
        'description': 'Lighting category (early-schema only).',
        'caveat': LIGHTING_CAVEAT,
    },
}


def harmonized_columns():
    '''Ordered list of the columns harmonize_all adds.'''
    return list(HARMONIZED_PROVENANCE.keys())
