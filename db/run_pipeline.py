'''End-to-end CLI: preflight -> create -> ingest -> build -> emit manifest.

Each stage is independently runnable via a flag; the default is a full run.
Idempotent: re-running with no new CSVs ingests 0 rows (sha256 guard) and
rebuilds treated + manifest to equivalent contents.

Examples
--------
    # Full run against DATABASE_URL from .env
    python db/run_pipeline.py

    # Just rebuild treated + emit manifest (raw already loaded)
    python db/run_pipeline.py --build-only --emit-only

    # Re-ingest the same file even if its sha256 already exists
    python db/run_pipeline.py --ingest-only --force

    # Clean slate (destructive; refuses without --yes in non-interactive use)
    python db/run_pipeline.py --reset --yes
'''
import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_REPO_ROOT / 'eda') not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / 'eda'))

import build_treated   # noqa: E402
import connection      # noqa: E402
import create_tables   # noqa: E402
import ingest_raw      # noqa: E402
import manifest        # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--database-url', help='Override DATABASE_URL for this run.')
    p.add_argument('--create-only', action='store_true',
                   help='Run only the schema-create stage.')
    p.add_argument('--ingest-only', action='store_true',
                   help='Run only the raw-ingest stage.')
    p.add_argument('--build-only', action='store_true',
                   help='Run only the treated-build stage.')
    p.add_argument('--emit-only', action='store_true',
                   help='Run only the manifest-emit stage.')
    p.add_argument('--force', action='store_true',
                   help='Re-ingest files whose sha256 already exists.')
    p.add_argument('--reset', action='store_true',
                   help='DESTRUCTIVE: drop all objects, then recreate '
                        'before running. Requires --yes (or an interactive '
                        'confirmation) to proceed.')
    p.add_argument('--yes', action='store_true',
                   help='Non-interactive confirmation for --reset.')
    p.add_argument('--csv-paths', nargs='*',
                   help='Override the default SGO CSV paths to ingest.')
    p.add_argument('--manifest-out',
                   default=str(manifest.DEFAULT_OUT_DIR),
                   help='Output directory for the manifest JSON files.')
    return p.parse_args(argv)


def _stage_selection(args):
    '''If any --*-only flag is set, run only the selected stages. Otherwise
    run all four. ("--build-only --emit-only" runs both, not neither.)'''
    onlys = [args.create_only, args.ingest_only, args.build_only, args.emit_only]
    if not any(onlys):
        return {'create': True, 'ingest': True, 'build': True, 'emit': True}
    return {
        'create': args.create_only,
        'ingest': args.ingest_only,
        'build': args.build_only,
        'emit': args.emit_only,
    }


def _confirm_reset(args):
    if args.yes:
        return True
    # Non-interactive guard: refuse silent destruction.
    if not sys.stdin.isatty():
        print('[run_pipeline] --reset is destructive and requires --yes when '
              'stdin is non-interactive. Aborting.', file=sys.stderr)
        return False
    resp = input('--reset will DROP every table + view. Type YES to proceed: ')
    return resp.strip() == 'YES'


def run(args=None):
    args = args or parse_args()

    if args.database_url:
        os.environ['DATABASE_URL'] = args.database_url

    # Preflight: fail fast if DATABASE_URL is missing / unreachable.
    try:
        engine = connection.get_engine()
    except RuntimeError as e:
        print(f'[run_pipeline] {e}', file=sys.stderr)
        return 2
    if not connection.ping(engine):
        print('[run_pipeline] preflight ping returned non-1; aborting.',
              file=sys.stderr)
        return 2
    print(f'[run_pipeline] preflight OK ({engine.url.get_backend_name()})')

    if args.reset:
        if not _confirm_reset(args):
            return 2
        print('[run_pipeline] reset: dropping all objects')
        create_tables.reset(engine, csv_paths=_resolved_csv_paths(args))

    stages = _stage_selection(args)
    summary = {'stages_run': [s for s, on in stages.items() if on]}

    if stages['create']:
        create_tables.create(engine, csv_paths=_resolved_csv_paths(args))
        summary['create'] = 'ok'

    if stages['ingest']:
        results = ingest_raw.ingest_all(
            engine, _resolved_csv_paths(args), force=args.force)
        summary['ingest'] = results

    if stages['build']:
        result = build_treated.build_treated(engine)
        summary['build'] = {
            'treated_rows': result['treated_rows'],
            'canonical_rows': result['canonical_rows'],
            'source_batch_ids': result['source_batch_ids'],
        }
        # Stash for downstream emit even when stages run independently.
        last_build = result
    else:
        last_build = None

    if stages['emit']:
        if last_build is None:
            # rebuild internally so emit-only against an already-populated DB
            # has fresh per-step deltas to record
            last_build = build_treated.build_treated(engine)
            summary.setdefault('build', {
                'treated_rows': last_build['treated_rows'],
                'canonical_rows': last_build['canonical_rows'],
                'source_batch_ids': last_build['source_batch_ids'],
            })
        paths = manifest.emit(engine, last_build, out_dir=args.manifest_out)
        summary['manifest'] = paths

    _print_summary(summary)
    return 0


def _resolved_csv_paths(args):
    if args.csv_paths:
        return [Path(p) for p in args.csv_paths]
    return list(create_tables.DEFAULT_CSV_PATHS)


def _print_summary(summary):
    print('\n=== run_pipeline summary ===')
    print(f'stages: {", ".join(summary["stages_run"])}')
    if 'create' in summary:
        print(f'create: {summary["create"]}')
    if 'ingest' in summary:
        for r in summary['ingest']:
            tag = 'skipped' if r['skipped'] else f'+{r["row_count"]} rows'
            print(f'ingest [{r["schema_version"] or "-"}] '
                  f'{r["source_file"]}: {tag}')
    if 'build' in summary:
        b = summary['build']
        print(f'build : {b["treated_rows"]} treated rows '
              f'({b["canonical_rows"]} canonical), '
              f'{len(b["source_batch_ids"])} source batch(es)')
    if 'manifest' in summary:
        m = summary['manifest']
        print(f'manifest: {m["cleaning_manifest"]}')
        print(f'columns : {m["column_dictionary"]}')


if __name__ == '__main__':   # pragma: no cover
    sys.exit(run())
