'''Offline batch: judge every incident row, store one verdict per
(report_id, fault_version) in ``fault_analysis``.

No ADS filter — the old ``automation_system_engaged = 'ADS'`` cut is dropped;
this judges **every** row in ``treated_incident_reports`` (a cheap Haiku batch,
a for-fun feature, not an analysis claim). Verdicts are idempotent on
(report_id, fault_version): a re-run of the same version UPSERTs, a new version
appends. Each LLM call is content-addressed cached by ``llm.py`` so re-runs pay
only for misses.

Runs in the ontology sidecar env (langgraph + langchain-anthropic + a loaded
``DATABASE_URL``)::

    source ~/claude_code_repos/my-uv-envs/avird-2026-ontology/.venv/Scripts/activate
    python fault/judge_batch.py --dry-run                 # count spend, no writes
    python fault/judge_batch.py --limit 5                 # eyeball 5 rows first
    python fault/judge_batch.py --fault-version mvp_0.01  # full run
'''
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
for _p in (_HERE, _REPO_ROOT / 'db', _REPO_ROOT / 'ontology'):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from graph import build_graph, judge_incident  # noqa: E402
from llm import CachedLLM  # noqa: E402

from format import format_incident  # noqa: E402  (isort: keep below ontology imports)

TABLE = 'fault_analysis'
TREATED_TABLE = 'treated_incident_reports'
REPORT_ID_COL = 'Report ID'
DEFAULT_FAULT_VERSION = 'mvp_0.01'
MAX_EXPLANATION_CHARS = 1000
ERROR_SENTINEL_TEXT = 'Error: model did not return a valid verdict.'

_UPSERT = text(
    f'INSERT INTO {TABLE} '
    '(report_id, fault_version, is_av_at_fault, av_fault_percentage, '
    'short_explanation_of_decision, model, created_at) '
    'VALUES (:report_id, :fault_version, :is_av_at_fault, '
    ':av_fault_percentage, :short_explanation_of_decision, :model, '
    ':created_at) '
    'ON CONFLICT (report_id, fault_version) DO UPDATE SET '
    'is_av_at_fault = excluded.is_av_at_fault, '
    'av_fault_percentage = excluded.av_fault_percentage, '
    'short_explanation_of_decision = excluded.short_explanation_of_decision, '
    'model = excluded.model, '
    'created_at = excluded.created_at'
)


def coerce_verdict(verdict) -> tuple[bool | None, float | None, str, bool]:
    '''Validate a verdict before write. Returns
    ``(is_av_at_fault, av_fault_percentage, explanation, is_error)``.

    Any type or range violation collapses to the explicit error sentinel
    (NULL verdict + NULL percentage + an error string) — never a guessed value.
    '''
    fault = verdict.is_av_at_fault
    pct = verdict.av_fault_percentage
    expl = verdict.short_explanation_of_decision

    if not isinstance(fault, bool):
        return None, None, ERROR_SENTINEL_TEXT, True
    # bool is a subclass of int — exclude it from the numeric check.
    if isinstance(pct, bool) or not isinstance(pct, (int, float)):
        return None, None, ERROR_SENTINEL_TEXT, True
    if not (0.0 <= float(pct) <= 1.0):
        return None, None, ERROR_SENTINEL_TEXT, True
    if not isinstance(expl, str) or not expl.strip():
        return None, None, ERROR_SENTINEL_TEXT, True

    return fault, float(pct), expl.strip()[:MAX_EXPLANATION_CHARS], False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_batch(rows, llm, engine, fault_version, *, report_id_col=REPORT_ID_COL):
    '''Judge each row and upsert its verdict. Pure of argparse/DB-bootstrap so
    tests drive it with a stub LLM + a sqlite engine.

    ``rows`` is an iterable of dict-like treated rows. Returns a stats dict.
    '''
    graph = build_graph(llm)
    stats = {'rows': 0, 'written': 0, 'errors': 0, 'dry_run_skipped': 0}

    for row in rows:
        stats['rows'] += 1
        report_id = row.get(report_id_col)
        verdict, error = judge_incident(graph, format_incident(row))

        if verdict is None and error is None:
            # Dry-run cache miss: counted by llm.stats, nothing to write.
            stats['dry_run_skipped'] += 1
            continue

        if verdict is None:
            is_fault, pct, expl, is_error = None, None, ERROR_SENTINEL_TEXT, True
        else:
            is_fault, pct, expl, is_error = coerce_verdict(verdict)

        if is_error:
            stats['errors'] += 1

        with engine.begin() as conn:
            conn.execute(_UPSERT, {
                'report_id': report_id,
                'fault_version': fault_version,
                'is_av_at_fault': is_fault,
                'av_fault_percentage': pct,
                'short_explanation_of_decision': expl,
                'model': llm.model_id,
                'created_at': _now_iso(),
            })
        stats['written'] += 1

    return stats


def _load_rows(engine, limit, report_id_col=REPORT_ID_COL):
    '''Load every treated row (or the first ``limit``) as plain dicts.'''
    import pandas as pd

    query = f'SELECT * FROM {TREATED_TABLE}'
    if limit:
        query += f' LIMIT {int(limit)}'
    df = pd.read_sql(query, engine)
    return df.to_dict(orient='records')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--fault-version', default=DEFAULT_FAULT_VERSION,
                   help='Version label for this verdict set (default mvp_0.01).')
    p.add_argument('--limit', type=int, default=None,
                   help='Judge only the first N rows (cheap iteration).')
    p.add_argument('--dry-run', action='store_true',
                   help='Count cache misses; zero LLM calls, zero DB writes.')
    args = p.parse_args(argv)

    import connection
    engine = connection.get_engine()
    rows = _load_rows(engine, args.limit)
    llm = CachedLLM(dry_run=args.dry_run)

    print(f'judging {len(rows)} row(s) '
          f'(version {args.fault_version}, model {llm.model_id}'
          f'{", dry-run" if args.dry_run else ""})')
    stats = run_batch(rows, llm, engine, args.fault_version)
    print(f'batch stats: {stats}')
    print(f'llm stats: {llm.stats}')
    if args.dry_run:
        print(f'--dry-run: {llm.stats["dry_run_misses"]} call(s) would be paid. '
              'No DB writes. Exit 0.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
