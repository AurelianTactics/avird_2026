'''Neo4j AuraDB projection: constraints, idempotent batched MERGE, reset.

The extraction artifact is the source of truth; the graph is a disposable
projection (AuraDB Free pauses after 72h idle and is eventually deleted). A
full rebuild is one command and touches no LLM:

    python ontology/graph_load.py --reset --yes --artifact <path>

Design:

- Every node carries a uniform ``key`` property (the stable key assigned at
  extraction). Uniqueness constraints (``CREATE CONSTRAINT ... IF NOT
  EXISTS``) are created per label *before* ingest — also makes MERGE indexed.
- Nodes load via ``UNWIND $rows MERGE (n:Label {key: row.key}) SET n +=
  row.props`` — merge on the key only, never the full property map, so
  re-loads are idempotent.
- Relationships MATCH both endpoints (labels resolved from the artifact's own
  key→type map) and MERGE the relationship.
- ``--reset`` is destructive and refuses without ``--yes`` when stdin is
  non-interactive (same convention as db/run_pipeline.py).

Statement *planning* is pure (returns Cypher + params); tests assert on the
plans with a stubbed driver and never need a live AuraDB.
'''
import argparse
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:  # optional: load .env if python-dotenv is available
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

DEFAULT_BATCH_SIZE = 500
EXTRACTIONS_DIR = _HERE / 'artifacts' / 'extractions'

NEO4J_ENV = ('NEO4J_URI', 'NEO4J_USERNAME', 'NEO4J_PASSWORD')

PAUSED_HINT = (
    'Could not reach Neo4j. If this is AuraDB Free, the instance pauses '
    'after ~72h idle - resume it in the Aura console (console.neo4j.io, '
    '~1-2 min) and retry. Also check NEO4J_URI / NEO4J_USERNAME / '
    'NEO4J_PASSWORD in .env.'
)


def get_driver(uri=None, username=None, password=None):
    import neo4j
    uri = uri or os.environ.get('NEO4J_URI')
    username = username or os.environ.get('NEO4J_USERNAME')
    password = password or os.environ.get('NEO4J_PASSWORD')
    missing = [name for name, val in zip(NEO4J_ENV, (uri, username, password))
               if not val]
    if missing:
        raise RuntimeError(
            f'{", ".join(missing)} not set. Put them in the root .env '
            f'(gitignored); values come from the Aura console.')
    return neo4j.GraphDatabase.driver(uri, auth=(username, password))


def preflight(driver):
    '''Fail fast with an actionable message when the instance is paused.'''
    try:
        driver.verify_connectivity()
    except Exception as e:
        raise RuntimeError(f'{PAUSED_HINT} ({type(e).__name__}: {e})') from e


# ---------------------------------------------------------------------------
# Artifact reading
# ---------------------------------------------------------------------------
def read_artifact(path):
    records = []
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def collect_instances(records):
    '''Flatten doc records → (node rows by label, rel rows, key→label map).

    Duplicate keys (column + narrative instance of the same entity, or the
    same shared entity across docs) collapse here so MERGE batches stay
    small; properties merge first-wins per key with later non-empty fills.
    '''
    nodes_by_label = {}
    key_to_label = {}
    for record in records:
        for ent in record['entities']:
            label = ent['type']
            key_to_label[ent['key']] = label
            rows = nodes_by_label.setdefault(label, {})
            row = rows.setdefault(ent['key'], {'key': ent['key'], 'props': {}})
            props = {'name': ent['name'], **(ent.get('properties') or {})}
            for k, v in props.items():
                row['props'].setdefault(k, v)

    rel_rows = []
    seen = set()
    for record in records:
        for rel in record['relationships']:
            ident = (rel['type'], rel['source_key'], rel['target_key'])
            if ident in seen:
                continue
            seen.add(ident)
            rel_rows.append({'type': rel['type'],
                             'source_key': rel['source_key'],
                             'target_key': rel['target_key']})
    return ({label: list(rows.values()) for label, rows in nodes_by_label.items()},
            rel_rows, key_to_label)


# ---------------------------------------------------------------------------
# Statement planning (pure)
# ---------------------------------------------------------------------------
def _constraint_name(label):
    return f'{label.lower()}_key_unique'


def plan_constraints(labels):
    return [
        (f'CREATE CONSTRAINT {_constraint_name(label)} IF NOT EXISTS '
         f'FOR (n:`{label}`) REQUIRE n.key IS UNIQUE', {})
        for label in sorted(labels)
    ]


def _batched(rows, batch_size):
    for i in range(0, len(rows), batch_size):
        yield rows[i:i + batch_size]


def plan_node_loads(nodes_by_label, batch_size=DEFAULT_BATCH_SIZE):
    statements = []
    for label in sorted(nodes_by_label):
        rows = sorted(nodes_by_label[label], key=lambda r: r['key'])
        for batch in _batched(rows, batch_size):
            statements.append((
                f'UNWIND $rows AS row '
                f'MERGE (n:`{label}` {{key: row.key}}) '
                f'SET n += row.props',
                {'rows': batch},
            ))
    return statements


def plan_relationship_loads(rel_rows, key_to_label,
                            batch_size=DEFAULT_BATCH_SIZE):
    '''Group by (type, source label, target label); skip unresolvable keys.'''
    grouped = {}
    skipped = []
    for row in rel_rows:
        src_label = key_to_label.get(row['source_key'])
        dst_label = key_to_label.get(row['target_key'])
        if src_label is None or dst_label is None:
            skipped.append(row)
            continue
        grouped.setdefault((row['type'], src_label, dst_label), []).append(
            {'source_key': row['source_key'], 'target_key': row['target_key']})

    statements = []
    for (rel_type, src_label, dst_label) in sorted(grouped):
        rows = sorted(grouped[(rel_type, src_label, dst_label)],
                      key=lambda r: (r['source_key'], r['target_key']))
        for batch in _batched(rows, batch_size):
            statements.append((
                f'UNWIND $rows AS row '
                f'MATCH (a:`{src_label}` {{key: row.source_key}}) '
                f'MATCH (b:`{dst_label}` {{key: row.target_key}}) '
                f'MERGE (a)-[r:`{rel_type}`]->(b)',
                {'rows': batch},
            ))
    return statements, skipped


def plan_load(records, batch_size=DEFAULT_BATCH_SIZE):
    '''Full load plan for an artifact: constraints, nodes, relationships.'''
    nodes_by_label, rel_rows, key_to_label = collect_instances(records)
    statements = plan_constraints(nodes_by_label.keys())
    statements += plan_node_loads(nodes_by_label, batch_size=batch_size)
    rel_statements, skipped = plan_relationship_loads(
        rel_rows, key_to_label, batch_size=batch_size)
    statements += rel_statements
    return statements, skipped


RESET_STATEMENT = ('MATCH (n) DETACH DELETE n', {})
COUNT_NODES = 'MATCH (n) RETURN count(n) AS n'
COUNT_RELS = 'MATCH ()-[r]->() RETURN count(r) AS n'


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def apply_statements(driver, statements):
    for query, params in statements:
        driver.execute_query(query, parameters_=params)


def graph_counts(driver):
    def scalar(query):
        result = driver.execute_query(query)
        records = list(result.records)
        return records[0]['n'] if records else 0
    return {'nodes': scalar(COUNT_NODES), 'relationships': scalar(COUNT_RELS)}


def _confirm_reset(yes):
    if yes:
        return True
    if not sys.stdin.isatty():
        print('[graph_load] --reset is destructive and requires --yes when '
              'stdin is non-interactive. Aborting.', file=sys.stderr)
        return False
    resp = input('--reset will DELETE every node + relationship. '
                 'Type YES to proceed: ')
    return resp.strip() == 'YES'


def _latest_artifact():
    candidates = sorted(EXTRACTIONS_DIR.glob('*.jsonl'))
    if not candidates:
        raise FileNotFoundError(
            f'no extraction artifacts under {EXTRACTIONS_DIR}; run '
            f'extract.py first')
    return candidates[-1]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--artifact', default=None,
                   help='Extraction artifact JSONL (default: latest).')
    p.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE)
    p.add_argument('--reset', action='store_true',
                   help='DESTRUCTIVE: wipe the graph before loading. '
                        'Requires --yes non-interactively.')
    p.add_argument('--yes', action='store_true',
                   help='Non-interactive confirmation for --reset.')
    p.add_argument('--counts-only', action='store_true',
                   help='Print node/relationship counts and exit.')
    args = p.parse_args(argv)

    driver = get_driver()
    try:
        preflight(driver)
        if args.counts_only:
            print(f'counts: {graph_counts(driver)}')
            return 0
        if args.reset:
            if not _confirm_reset(args.yes):
                return 2
            print('[graph_load] reset: deleting all nodes + relationships')
            driver.execute_query(RESET_STATEMENT[0])

        artifact = Path(args.artifact) if args.artifact else _latest_artifact()
        records = read_artifact(artifact)
        statements, skipped = plan_load(records, batch_size=args.batch_size)
        print(f'[graph_load] {artifact.name}: {len(records)} docs, '
              f'{len(statements)} statements')
        if skipped:
            print(f'[graph_load] WARNING: {len(skipped)} relationships '
                  f'reference keys absent from the artifact; skipped')
        apply_statements(driver, statements)
        print(f'counts after load: {graph_counts(driver)}')
        return 0
    finally:
        driver.close()


if __name__ == '__main__':
    sys.exit(main())
