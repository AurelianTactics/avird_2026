'''End-to-end ontology CLI: seed -> discover -> [human gate] -> extract ->
load -> eval.

Each stage is independently runnable via a flag; the default is a full run
that *stops at the human approval gate* when no frozen schema exists yet
(extraction never runs against a draft). Stage flags follow the
db/run_pipeline.py convention: any ``--*-only`` flag selects exactly the
flagged stages ("--extract-only --load-only" runs both).

Examples
--------
    # Schema induction (cheap preflight first)
    python ontology/run_pipeline.py --seed-only
    python ontology/run_pipeline.py --discover-only --dry-run

    # After approving ontology/schema/v001.yaml:
    python ontology/run_pipeline.py --extract-only --limit 100 --include-golden
    python ontology/run_pipeline.py --load-only --reset --yes
    python ontology/run_pipeline.py --eval-only
'''
import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

DEFAULT_SCHEMA = _HERE / 'schema' / 'v001.yaml'
STAGES = ('seed', 'discover', 'extract', 'load', 'eval')


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for stage in STAGES:
        p.add_argument(f'--{stage}-only', action='store_true',
                       help=f'Run only the {stage} stage.')
    p.add_argument('--schema', default=str(DEFAULT_SCHEMA),
                   help='Frozen schema path (drafts are refused).')
    p.add_argument('--limit', type=int, default=100,
                   help='Docs for extraction (0 = full corpus).')
    p.add_argument('--sample', type=int, default=None,
                   help='Narrative sample size for discovery.')
    p.add_argument('--include-golden', action='store_true',
                   help='Extraction doc set supersets the golden splits.')
    p.add_argument('--dry-run', action='store_true',
                   help='Preflight: counts and cache misses, zero LLM calls.')
    p.add_argument('--heldout', action='store_true',
                   help='Eval scores the held-out split (final numbers only).')
    p.add_argument('--artifact', default=None,
                   help='Extraction artifact for load/eval (default: latest).')
    p.add_argument('--reset', action='store_true',
                   help='DESTRUCTIVE: wipe the graph before loading. '
                        'Requires --yes non-interactively.')
    p.add_argument('--yes', action='store_true',
                   help='Non-interactive confirmation for --reset.')
    return p.parse_args(argv)


def stage_selection(args):
    '''Any --*-only flag selects exactly the flagged stages; none = all.'''
    onlys = {stage: getattr(args, f'{stage}_only') for stage in STAGES}
    if not any(onlys.values()):
        return {stage: True for stage in STAGES}
    return onlys


def frozen_schema_ready(schema_path):
    return Path(schema_path).exists()


def run(argv=None):
    args = parse_args(argv)
    stages = stage_selection(args)
    ran = []

    if stages['seed']:
        import seed_schema
        print('=== stage: seed ===')
        seed_schema.main([])
        ran.append('seed')

    if stages['discover']:
        import discover
        print('=== stage: discover ===')
        discover_args = []
        if args.sample is not None:
            discover_args += ['--sample', str(args.sample)]
        if args.dry_run:
            discover_args += ['--dry-run']
        rc = discover.main(discover_args)
        if rc:
            return rc
        ran.append('discover')

    needs_schema = [s for s in ('extract', 'load', 'eval') if stages[s]]
    if needs_schema and not frozen_schema_ready(args.schema):
        print(f'[run_pipeline] stages {needs_schema} need the frozen schema '
              f'{args.schema}, which does not exist yet.\n'
              f'Approve the draft first: edit '
              f'ontology/schema/drafts/v001-draft.yaml, add competency '
              f'questions, save as {args.schema}, and commit. '
              f'(Stages run so far: {ran or "none"}.)', file=sys.stderr)
        return 0 if ran else 2

    if stages['extract']:
        import extract
        print('=== stage: extract ===')
        extract_args = ['--schema', args.schema, '--limit', str(args.limit)]
        if args.include_golden:
            extract_args += ['--include-golden']
        if args.dry_run:
            extract_args += ['--dry-run']
        rc = extract.main(extract_args)
        if rc:
            return rc
        ran.append('extract')

    if args.dry_run and (stages['load'] or stages['eval']):
        print('[run_pipeline] --dry-run: skipping load/eval stages '
              '(they spend no LLM tokens; run them without --dry-run)')

    if stages['load'] and not args.dry_run:
        import graph_load
        print('=== stage: load ===')
        load_args = []
        if args.artifact:
            load_args += ['--artifact', args.artifact]
        if args.reset:
            load_args += ['--reset']
        if args.yes:
            load_args += ['--yes']
        rc = graph_load.main(load_args)
        if rc:
            return rc
        ran.append('load')

    if stages['eval'] and not args.dry_run:
        import evaluate
        import graph_load
        print('=== stage: eval ===')
        artifact = args.artifact or str(graph_load._latest_artifact())
        eval_args = ['extraction', '--artifact', artifact]
        if args.heldout:
            eval_args += ['--heldout']
        rc = evaluate.main(eval_args)
        if rc:
            return rc
        ran.append('eval')

    print(f'\n=== run_pipeline summary ===\nstages run: {", ".join(ran)}')
    return 0


if __name__ == '__main__':
    sys.exit(run())
