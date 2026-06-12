'''Corpus access for the ontology pipeline.

Loads canonical incident rows (``is_latest_of_multiple_report = TRUE``) from
``treated_incident_reports``, cleans the narrative text deterministically, and
assigns stable document keys. The preprocessed text is what extraction quotes
verify against and what the LLM cache keys on, so every transform here must be
byte-stable across runs.

Skip semantics: whole-cell-redacted or empty-after-cleaning docs are *marked*
(``skip_reason``), never silently dropped — downstream stages still emit their
deterministic structured-column entities, they just never reach the LLM.

Run a smoke check from the repo root (needs ``DATABASE_URL``)::

    python ontology/corpus.py --limit 5
'''
import argparse
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
for _p in (_REPO_ROOT / 'db', _REPO_ROOT / 'eda'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import pandas as pd  # noqa: E402

from eda_utils_sgo import is_redacted  # noqa: E402

TREATED_TABLE = 'treated_incident_reports'
MERGED_NARRATIVE_COL = 'Narrative - Same Incident ID'
NARRATIVE_COL = 'Narrative'
SAME_INCIDENT_COL = 'Same Incident ID'
REPORT_ID_COL = 'Report ID'
CANONICAL_FLAG_COL = 'is_latest_of_multiple_report'

# Matches eda_utils_dedupe._DEFAULT_NARRATIVE_SEP with whatever whitespace
# survived storage around it.
_SEPARATOR_RE = re.compile(r'\s*-{3,}\s*next report\s*-{3,}\s*', re.IGNORECASE)
# Inline redaction spans: bracketed [XXX] or bare runs of 3+ X's.
_INLINE_REDACTION_RE = re.compile(r'\[X{2,}\]|\bX{3,}\b')

LONG_TEXT_CHARS = 8000

SKIP_REDACTED = 'skipped_redacted'
SKIP_EMPTY = 'skipped_empty'
SKIP_NO_KEY = 'skipped_no_key'

# Structured columns carried on each doc for deterministic (no-LLM) entity
# seeding. The seed schema (seed_schema.py) and extraction's column-provenance
# entities both draw from this list; extend it there and here together.
STRUCTURED_COLUMNS = [
    'Report ID', 'Same Incident ID', 'Reporting Entity', 'Report Submission Date',
    'master_entity', 'Operating Entity Clean',
    'VIN', 'Make Clean', 'Model Clean', 'Model Year', 'Mileage',
    'automation_system_type', 'automation_engaged_clean',
    'Driver / Operator Type',
    'incident_date', 'Incident Time (24:00)',
    'City', 'State', 'Zip Code', 'Address',
    'Roadway Type', 'Roadway Surface', 'Roadway Description',
    'Posted Speed Limit (MPH)', 'Lighting',
    'weather_clear_clean', 'weather_snow_clean', 'weather_cloudy_clean',
    'weather_fog_smoke_clean', 'weather_rain_clean', 'weather_severe_wind_clean',
    'weather_unknown_clean',
    'roadway_wet_surface_clean', 'roadway_work_zone_clean',
    'roadway_degraded_marking_clean', 'roadway_traffic_incident_clean',
    'Crash With', 'Highest Injury Severity Alleged',
    'sv_precrash_speed_mph', 'SV Pre-Crash Movement', 'CP Pre-Crash Movement',
    'CP Contact Area - Front', 'SV Contact Area - Front',
]


@dataclass
class Doc:
    '''One canonical incident: cleaned narrative + structured-column payload.'''
    doc_key: str
    report_id: str | None
    same_incident_id: str | None
    text: str                       # '' when skipped
    text_sha256: str
    skip_reason: str | None = None
    flags: list = field(default_factory=list)
    row: dict = field(default_factory=dict)


@dataclass
class Corpus:
    docs: list
    snapshot: dict                  # built_at / source_batch_ids for run records
    skip_counts: dict


def _cell(value):
    '''NaN-tolerant cell read: stripped string or None.'''
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if pd.isna(value):
        return None
    s = str(value).strip()
    return s or None


def _to_native(value):
    '''Coerce numpy scalars to JSON-safe Python natives.'''
    if hasattr(value, 'item'):
        return value.item()
    return value


def _normalize_whitespace(s):
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def _segment_is_redacted(segment):
    return bool(is_redacted(pd.Series([segment])).iloc[0])


def preprocess_narrative(raw):
    '''Clean one narrative cell deterministically.

    Returns ``(text, skip_reason)``. Splits merged narratives on the
    ``--- next report ---`` separator, drops whole-cell-redacted segments
    (detected before inline-span stripping so the sentinel text is intact),
    strips inline ``[XXX]`` spans, and normalizes whitespace. ``text`` is ''
    whenever ``skip_reason`` is set.
    '''
    raw = _cell(raw)
    if raw is None:
        return '', SKIP_EMPTY

    segments = [seg for seg in _SEPARATOR_RE.split(raw) if seg.strip()]
    saw_redacted = False
    cleaned = []
    for seg in segments:
        if _segment_is_redacted(seg):
            saw_redacted = True
            continue
        seg = _INLINE_REDACTION_RE.sub('', seg)
        seg = _normalize_whitespace(seg)
        if seg:
            cleaned.append(seg)

    if not cleaned:
        return '', SKIP_REDACTED if saw_redacted else SKIP_EMPTY
    return '\n\n'.join(cleaned), None


def corpus_from_frame(df, limit=None, doc_keys=None):
    '''Build a Corpus from a treated-table frame (the hermetic core).

    Rows are keyed by ``Same Incident ID`` (fallback ``Report ID``), sorted by
    key for stable ordering, then optionally filtered to an explicit
    ``doc_keys`` list or truncated to ``limit``. Requesting an absent doc key
    raises — eval runs must not silently shrink.
    '''
    skip_counts = {}

    def bump(reason):
        skip_counts[reason] = skip_counts.get(reason, 0) + 1

    keyed = {}
    for _, r in df.iterrows():
        # r.get is None-safe for absent columns (schema drift)
        same_id = _cell(r.get(SAME_INCIDENT_COL))
        report_id = _cell(r.get(REPORT_ID_COL))
        key = same_id or report_id
        if key is None:
            bump(SKIP_NO_KEY)
            continue
        if key in keyed:
            bump('skipped_duplicate_key')
            continue
        keyed[key] = (r, same_id, report_id)

    ordered_keys = sorted(keyed)
    if doc_keys is not None:
        missing = [k for k in doc_keys if k not in keyed]
        if missing:
            raise ValueError(f'doc keys not in corpus: {missing[:5]}'
                             f'{"..." if len(missing) > 5 else ""}')
        ordered_keys = list(doc_keys)
    elif limit is not None:
        ordered_keys = ordered_keys[:limit]

    docs = []
    for key in ordered_keys:
        r, same_id, report_id = keyed[key]
        raw = _cell(r.get(MERGED_NARRATIVE_COL)) or _cell(r.get(NARRATIVE_COL))
        text, skip_reason = preprocess_narrative(raw)
        if skip_reason:
            bump(skip_reason)
        flags = ['long_text'] if len(text) > LONG_TEXT_CHARS else []
        row = {}
        for col in STRUCTURED_COLUMNS:
            val = r.get(col)
            cell = _cell(val)
            if cell is not None:
                row[col] = _to_native(val) if not isinstance(val, str) else cell
        docs.append(Doc(
            doc_key=key,
            report_id=report_id,
            same_incident_id=same_id,
            text=text,
            text_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
            skip_reason=skip_reason,
            flags=flags,
            row=row,
        ))

    first = df.iloc[0] if len(df) else {}
    snapshot = {
        'built_at': _cell(first.get('built_at') if hasattr(first, 'get') else None),
        'source_batch_ids': _cell(
            first.get('source_batch_ids') if hasattr(first, 'get') else None),
        'n_canonical_rows': int(len(df)),
    }
    return Corpus(docs=docs, snapshot=snapshot, skip_counts=skip_counts)


def load_corpus(engine=None, limit=None, doc_keys=None, table=TREATED_TABLE):
    '''Load canonical rows from Postgres and build the Corpus.'''
    if engine is None:
        import connection
        engine = connection.get_engine()
    query = f'SELECT * FROM {table} WHERE "{CANONICAL_FLAG_COL}" = TRUE'
    df = pd.read_sql(query, engine)
    return corpus_from_frame(df, limit=limit, doc_keys=doc_keys)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--limit', type=int, default=None,
                   help='Load only the first N docs (stable ordering).')
    args = p.parse_args(argv)

    corpus = load_corpus(limit=args.limit)
    print(f'docs: {len(corpus.docs)}')
    print(f'snapshot: {corpus.snapshot}')
    print(f'skips: {corpus.skip_counts}')
    for doc in corpus.docs[:3]:
        preview = doc.text[:160].replace('\n', ' ')
        print(f'- {doc.doc_key} [{doc.skip_reason or "ok"}] {preview}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
