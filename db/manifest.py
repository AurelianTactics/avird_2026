'''Emit machine-readable cleaning artifacts.

Two JSON files are written under ``docs/data-dictionary/`` so the future
data-dictionary page has a single source of truth that stays in lock-step with
the pipeline:

  cleaning_manifest.json   ordered list of pipeline steps (name, description,
                           rule_summary, input/output columns, rows_in/affected)
                           with the engagement + lighting semantic caveats
                           attached to their relevant steps.

  column_dictionary.json   one entry per column of treated_incident_reports
                           (name, source_type, derived_from, description,
                           sql_type, optional caveat).
'''
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import inspect

_EDA_DIR = Path(__file__).resolve().parents[1] / 'eda'
if str(_EDA_DIR) not in sys.path:
    sys.path.insert(0, str(_EDA_DIR))

import eda_utils_harmonize as hz   # noqa: E402
import eda_utils_targets           # noqa: E402

import build_treated               # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = _REPO_ROOT / 'docs' / 'data-dictionary'

# Per-step caveat overlays added on top of build_treated's recorded deltas.
_STEP_CAVEATS = {
    'harmonize_engagement': hz.ENGAGEMENT_CAVEAT,
    'harmonize_lighting': hz.LIGHTING_CAVEAT,
}

# Source_type tags used by the column dictionary.
SRC_RAW = 'raw'
SRC_CLEANED = 'cleaned'
SRC_HARMONIZED = 'harmonized'
SRC_TARGET = 'target'
SRC_FLAG = 'flag'
SRC_PROVENANCE = 'provenance'

# Fixed-name treated columns whose provenance is known statically.
FLAG_COLUMNS = {
    'is_latest_of_multiple_report': {
        'derived_from': [
            'Same Incident ID', 'Reporting Entity', 'Incident Date',
            'Incident Time (24:00)', 'VIN',
            'Report Submission Date', 'Report Version', 'Report ID',
        ],
        'description': (
            'True for the canonical row of each incident: the most recent '
            'report of a multi-report group, and every single-report incident.'
        ),
    },
    'has_multiple_reports': {
        'derived_from': ['Same Incident ID', 'Reporting Entity', 'Incident Date',
                         'Incident Time (24:00)', 'VIN'],
        'description': 'True when the incident has more than one report.',
    },
}

MERGED_NARRATIVE_COL = 'Narrative - Same Incident ID'

PROMOTED_PROVENANCE = {
    'incident_date': {
        'derived_from': ['Incident Date'],
        'description': 'pd.to_datetime(Incident Date).',
    },
    'lat_numeric': {
        'derived_from': ['Latitude'],
        'description': 'pd.to_numeric(Latitude).',
    },
    'lon_numeric': {
        'derived_from': ['Longitude'],
        'description': 'pd.to_numeric(Longitude).',
    },
    'sv_precrash_speed_mph': {
        'derived_from': ['SV Precrash Speed (MPH)'],
        'description': 'pd.to_numeric(SV Precrash Speed (MPH)).',
    },
}

PROVENANCE_COLUMNS = {
    'source_batch_ids': {
        'derived_from': ['ingest_batches.batch_id'],
        'description': (
            'Comma-separated list of ingest batches that fed the rows '
            'this treated build was derived from.'
        ),
    },
    'built_at': {
        'derived_from': [],
        'description': 'UTC ISO-8601 timestamp of when this treated table was built.',
    },
}

# Fixed treatment columns whose provenance is known statically.
_TREATMENT_FIXED = {
    'master_entity': {
        'derived_from': ['Operating Entity', 'Reporting Entity'],
        'description': (
            'Canonical entity display name (drops legal suffixes, '
            'collapses dotted acronyms, fuzzy-clusters near-duplicates).'
        ),
    },
    'Make Model': {
        'derived_from': ['Make', 'Model'],
        'description': 'Normalized "<Make> | <Model>" combination string.',
    },
    MERGED_NARRATIVE_COL: {
        'derived_from': ['Narrative'],
        'description': (
            'All unique narratives for the incident, latest first, '
            'attached to the canonical row only.'
        ),
    },
}

_DEFAULT_SV_THRESHOLD = 10

# eda_utils_targets keys -> (column name, derived_from, description).
_TARGET_INFO = {
    'no_injury': (
        ['Highest Injury Severity Alleged'],
        'Binary 0/1: no injury / property-damage-only.'),
    'injury_reported': (
        ['Highest Injury Severity Alleged'],
        'Binary 0/1: any injury severity reported (Minor/Moderate/Serious/Fatality).'),
    'multi_class_injury': (
        ['Highest Injury Severity Alleged'],
        'Ordinal 0-4: 0=none/unknown, 1=Minor, 2=Moderate, 3=Serious, 4=Fatality.'),
    'binary_airbag': (
        list(eda_utils_targets.AIRBAG_COLS),
        'Binary 0/1: any airbag deployed (yes-substring across both schema variants).'),
    'binary_towed': (
        list(eda_utils_targets.TOWED_COLS),
        'Binary 0/1: any vehicle towed (yes-substring across both schema variants).'),
    'sv_speed': (
        ['SV Precrash Speed (MPH)'],
        f'Binary 0/1: SV pre-crash speed >= {_DEFAULT_SV_THRESHOLD} MPH.'),
    'non_trivial': (
        ['Highest Injury Severity Alleged'] + list(eda_utils_targets.AIRBAG_COLS)
        + list(eda_utils_targets.TOWED_COLS)
        + ['SV Precrash Speed (MPH)', 'Crash With'],
        'Binary 0/1: OR of injury / airbag / towed / SV speed>=threshold / pedestrian crash.'),
}


def _target_columns():
    '''Resolve TARGET_COL_NAMES (which has a {threshold} format placeholder).'''
    out = {}
    for key, name in eda_utils_targets.TARGET_COL_NAMES.items():
        out[name.format(threshold=_DEFAULT_SV_THRESHOLD)] = key
    return out


# ---------------------------------------------------------------------------
# Column classification
# ---------------------------------------------------------------------------
def _classify(name, target_lookup):
    if name in target_lookup:
        key = target_lookup[name]
        derived_from, description = _TARGET_INFO[key]
        return SRC_TARGET, derived_from, description, None

    if name in FLAG_COLUMNS:
        info = FLAG_COLUMNS[name]
        return SRC_FLAG, info['derived_from'], info['description'], None

    if name in PROVENANCE_COLUMNS:
        info = PROVENANCE_COLUMNS[name]
        return SRC_PROVENANCE, info['derived_from'], info['description'], None

    if name in hz.HARMONIZED_PROVENANCE:
        info = hz.HARMONIZED_PROVENANCE[name]
        return SRC_HARMONIZED, info['derived_from'], info['description'], info.get('caveat')

    if name in PROMOTED_PROVENANCE:
        info = PROMOTED_PROVENANCE[name]
        return SRC_CLEANED, info['derived_from'], info['description'], None

    if name in _TREATMENT_FIXED:
        info = _TREATMENT_FIXED[name]
        return SRC_CLEANED, info['derived_from'], info['description'], None

    if name.endswith(' Clean'):
        src = name[:-len(' Clean')]
        return (
            SRC_CLEANED, [src],
            f'Normalized {src!r} (lowercased, trimmed, legal suffixes dropped).',
            None,
        )

    # Default: raw passthrough from the source CSV.
    return (
        SRC_RAW, [name],
        'Raw passthrough from SGO source CSV (stored as TEXT in the raw layer).',
        None,
    )


# ---------------------------------------------------------------------------
# Manifest construction
# ---------------------------------------------------------------------------
def _build_cleaning_manifest(build_result):
    steps = []
    for s in build_result['steps']:
        entry = dict(s)
        if s['step'] in _STEP_CAVEATS:
            entry['caveat'] = _STEP_CAVEATS[s['step']]
        steps.append(entry)
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'pipeline_version': 1,
        'source_batch_ids': build_result['source_batch_ids'],
        'built_at': build_result['built_at'],
        'steps': steps,
    }


def _build_column_dictionary(engine, build_result, table=build_treated.TREATED_TABLE):
    target_lookup = _target_columns()
    insp = inspect(engine)
    columns = []
    for col in insp.get_columns(table):
        name = col['name']
        sql_type = str(col['type'])
        src_type, derived_from, description, caveat = _classify(name, target_lookup)
        entry = {
            'name': name,
            'source_type': src_type,
            'derived_from': list(derived_from),
            'description': description,
            'sql_type': sql_type,
        }
        if caveat:
            entry['caveat'] = caveat
        columns.append(entry)
    return {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source_batch_ids': build_result['source_batch_ids'],
        'built_at': build_result['built_at'],
        'treated_table': table,
        'columns': columns,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def emit(engine, build_result, out_dir=DEFAULT_OUT_DIR):
    '''Write both JSON artifacts under *out_dir*; return their paths.'''
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cleaning = _build_cleaning_manifest(build_result)
    columns = _build_column_dictionary(engine, build_result)

    cleaning_path = out_dir / 'cleaning_manifest.json'
    columns_path = out_dir / 'column_dictionary.json'
    cleaning_path.write_text(json.dumps(cleaning, indent=2, default=str))
    columns_path.write_text(json.dumps(columns, indent=2, default=str))

    print(f'[manifest] wrote {cleaning_path}')
    print(f'[manifest] wrote {columns_path}')
    return {
        'cleaning_manifest': str(cleaning_path),
        'column_dictionary': str(columns_path),
    }
