'''Build the treated layer from the raw `latest` view.

Reads ``raw_incident_reports_latest`` into a DataFrame, promotes a few
high-value raw columns to real types, then runs the treatment pipeline:

    promote typed cols
    -> flag_incident_reports        (eda_utils_dedupe)   canonical-row flags
    -> apply_all_treatments         (eda_utils_treatment) cleaned org/state, master_entity, Make Model
    -> harmonize_* (5 families)      (eda_utils_harmonize) *_clean columns
    -> add_all_targets              (eda_utils_targets)  7 target columns

Per-step row/column deltas are captured for the cleaning manifest (U7). The
full frame (all rows, flag-distinguished -- never collapsed) is written to
``treated_incident_reports`` via to_sql(if_exists='replace'). The promoted +
flag columns get explicit SQL types (see ``TREATED_COLUMN_TYPES``) so the table
honors the ``003_treated_incident_reports.sql`` DATE/NUMERIC/BOOLEAN contract
instead of whatever pandas would infer; the remaining columns fall back to
pandas-inferred TEXT. Provenance (``source_batch_ids``, ``built_at``) is stamped
on every row.
'''
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import Boolean, Date, Numeric

_EDA_DIR = Path(__file__).resolve().parents[1] / 'eda'
if str(_EDA_DIR) not in sys.path:
    sys.path.insert(0, str(_EDA_DIR))

import eda_utils_dedupe       # noqa: E402
import eda_utils_treatment    # noqa: E402
import eda_utils_harmonize    # noqa: E402
import eda_utils_targets      # noqa: E402

TREATED_TABLE = 'treated_incident_reports'
LATEST_VIEW = 'raw_incident_reports_latest'
_RANK_HELPER_COL = '_latest_rank'

# Raw column -> promoted typed column. Coerced before the pipeline runs so the
# treated table lands DATE / NUMERIC where useful. The typed lat/lon names use
# the `_numeric` suffix to avoid a sqlite case-insensitive collision with the
# raw "Latitude"/"Longitude" passthrough columns (Postgres distinguishes them
# when quoted; sqlite folds case even with quotes).
_PROMOTED = {
    'Incident Date': 'incident_date',
    'Latitude': 'lat_numeric',
    'Longitude': 'lon_numeric',
    'SV Precrash Speed (MPH)': 'sv_precrash_speed_mph',
}

# Explicit SQL types for the promoted + flag columns, applied via
# to_sql(dtype=...) on every rebuild. Without this, to_sql(if_exists='replace')
# lets pandas infer types (TIMESTAMP / FLOAT / INTEGER), silently diverging from
# the 003_treated_incident_reports.sql contract and from the sql_type reported
# by the column dictionary. Keep the column->type pairs in sync with 003.
TREATED_COLUMN_TYPES = {
    'incident_date': Date(),
    'lat_numeric': Numeric(),
    'lon_numeric': Numeric(),
    'sv_precrash_speed_mph': Numeric(),
    'is_latest_of_multiple_report': Boolean(),
    'has_multiple_reports': Boolean(),
}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
def read_latest(engine, view=LATEST_VIEW):
    '''Read the latest-per-natural-key view; drop the view's rank helper col.'''
    with engine.connect() as conn:
        df = pd.read_sql(f'SELECT * FROM {view}', conn)
    if _RANK_HELPER_COL in df.columns:
        df = df.drop(columns=[_RANK_HELPER_COL])
    return df


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------
def _promote_typed_columns(df):
    cols = {}
    if 'Incident Date' in df.columns:
        cols['incident_date'] = pd.to_datetime(
            df['Incident Date'], errors='coerce', format='mixed')
    if 'Latitude' in df.columns:
        cols['lat_numeric'] = pd.to_numeric(df['Latitude'], errors='coerce')
    if 'Longitude' in df.columns:
        cols['lon_numeric'] = pd.to_numeric(df['Longitude'], errors='coerce')
    if 'SV Precrash Speed (MPH)' in df.columns:
        cols['sv_precrash_speed_mph'] = pd.to_numeric(
            df['SV Precrash Speed (MPH)'], errors='coerce')
    return df.assign(**cols)


def _doc(fn):
    '''First paragraph of a function docstring, whitespace-collapsed.'''
    para = (fn.__doc__ or '').strip().split('\n\n')[0]
    return ' '.join(para.split())


# (step name, callable, human description, rule_summary, input_columns)
def _pipeline():
    return [
        ('promote_typed_columns', _promote_typed_columns,
         'Promote high-value raw TEXT columns to real types.',
         'pd.to_datetime / pd.to_numeric on the listed raw columns (errors->NaT/NaN).',
         list(_PROMOTED)),
        ('dedupe_flag', eda_utils_dedupe.flag_incident_reports,
         'Flag the canonical row per incident without dropping rows.',
         _doc(eda_utils_dedupe.flag_incident_reports),
         ['Same Incident ID', 'Reporting Entity', 'Incident Date',
          'Incident Time (24:00)', 'VIN', 'Report Submission Date',
          'Report Version', 'Report ID', 'Narrative']),
        ('treatments', eda_utils_treatment.apply_all_treatments,
         'Append cleaned org/state columns, master_entity and Make Model.',
         _doc(eda_utils_treatment.apply_all_treatments),
         ['Operating Entity', 'Reporting Entity', 'Investigating Agency',
          'State or Local Permit', 'Make', 'Model', 'State']),
        ('harmonize_engagement', eda_utils_harmonize.harmonize_engagement,
         'Harmonize automation engagement across schema versions.',
         _doc(eda_utils_harmonize.harmonize_engagement),
         ['Engagement Status', 'Automation System Engaged?']),
        ('harmonize_belted', eda_utils_harmonize.harmonize_belted,
         'Harmonize passenger belt status across schema versions.',
         _doc(eda_utils_harmonize.harmonize_belted),
         ['SV Were All Passengers Belted?', 'Were All Passengers Belted?']),
        ('harmonize_weather', eda_utils_harmonize.harmonize_weather,
         'Harmonize weather flags onto a shared vocabulary.',
         _doc(eda_utils_harmonize.harmonize_weather),
         ['Weather - Clear', 'Weather - Cloudy', 'Weather - Partly Cloudy',
          'Weather - Fog/Smoke', 'Weather - Fog/Smoke/Haze',
          'Weather - Unknown', 'Weather - Unk - See Narrative']),
        ('harmonize_roadway', eda_utils_harmonize.harmonize_roadway,
         'Harmonize roadway condition flags across schema versions.',
         _doc(eda_utils_harmonize.harmonize_roadway),
         ['Roadway Surface', 'Roadway Description', 'Roadway-Wet Surface Condition',
          'Roadway-Work Zone', 'Roadway-Missing/Degraded Marking',
          'Roadway-Traffic Incident']),
        ('harmonize_lighting', eda_utils_harmonize.harmonize_lighting,
         'Carry the early-only Lighting column to lighting_clean.',
         _doc(eda_utils_harmonize.harmonize_lighting),
         ['Lighting']),
        ('targets', eda_utils_targets.add_all_targets,
         'Append the 7 candidate target columns.',
         _doc(eda_utils_targets.add_all_targets),
         ['Highest Injury Severity Alleged', 'Crash With', 'SV Precrash Speed (MPH)',
          'Any Air Bags Deployed?', 'CP Any Air Bags Deployed?',
          'SV Any Air Bags Deployed?', 'Was Any Vehicle Towed?',
          'CP Was Vehicle Towed?', 'SV Was Vehicle Towed?']),
    ]


def _is_active(series):
    '''Boolean mask of "meaningfully set" cells (for rows_affected stats).'''
    if series.dtype == bool:
        return series.fillna(False)
    if pd.api.types.is_numeric_dtype(series):
        return series.fillna(0) != 0
    return series.notna() & (series.astype('string').str.strip() != '')


def _rows_affected(df, cols):
    if not cols:
        return 0
    active = pd.Series(False, index=df.index)
    for c in cols:
        active = active | _is_active(df[c]).fillna(False)
    return int(active.sum())


def build_treated_frame(df_latest):
    '''Run the full pipeline. Returns (treated_df, steps) where steps is the
    ordered per-stage delta list consumed by the cleaning manifest.'''
    steps = []
    df = df_latest
    for name, fn, description, rule_summary, input_columns in _pipeline():
        before = set(df.columns)
        df = fn(df)
        new_cols = [c for c in df.columns if c not in before]
        steps.append({
            'step': name,
            'description': description,
            'rule_summary': rule_summary,
            'input_columns': input_columns,
            'output_columns': new_cols,
            'rows_in': int(len(df)),
            'rows_affected': _rows_affected(df, new_cols),
        })
    return df, steps


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
def build_treated(engine):
    '''End-to-end: read latest -> pipeline -> write treated table.

    Returns a result dict: treated_rows, canonical_rows, source_batch_ids,
    built_at, steps. Raises ValueError if the latest view is empty.'''
    df_latest = read_latest(engine)
    if df_latest.empty:
        raise ValueError(
            f'{LATEST_VIEW} is empty; ingest raw data before building treated.'
        )

    source_batch_ids = sorted(
        df_latest['ingest_batch_id'].dropna().astype(str).unique().tolist()
    )
    treated_df, steps = build_treated_frame(df_latest)

    built_at = datetime.now(timezone.utc).isoformat()
    out = treated_df.assign(
        source_batch_ids=','.join(source_batch_ids) if source_batch_ids else None,
        built_at=built_at,
    )
    out.to_sql(
        TREATED_TABLE, engine, if_exists='replace', index=False,
        dtype={c: t for c, t in TREATED_COLUMN_TYPES.items() if c in out.columns},
    )

    canonical_rows = int(treated_df['is_latest_of_multiple_report'].sum())
    print(f'[build_treated] wrote {len(out)} rows to {TREATED_TABLE} '
          f'({canonical_rows} canonical), {len(steps)} pipeline steps')
    return {
        'treated_rows': int(len(out)),
        'canonical_rows': canonical_rows,
        'source_batch_ids': source_batch_ids,
        'built_at': built_at,
        'steps': steps,
    }
