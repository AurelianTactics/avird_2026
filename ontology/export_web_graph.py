'''Export the ontology as static graph data for the web page.

This is a *read-only projection* for `apps/web/public/ontology/index.html`. It
turns three things the pipeline already produces into one `data.js` file:

  - `schema/v001.yaml`        -> the ontology meta-graph (types + patterns)
  - latest extraction artifact -> a few real incident graphs (instances)
  - run summary + eval results -> the headline numbers shown on the page

The page is deliberately decoupled from Neo4j: AuraDB Free pauses after 72h and
is eventually deleted, and the extraction JSONL is the source of truth (see
ontology/CLAUDE.md). So the web graph is rebuilt from files, never from a live
database, and works even when Aura is asleep or gone.

Output is a single `window.ONTOLOGY_DATA = {...}` assignment so the HTML can
load it with a plain <script src> tag (works even when the file is opened
directly from disk, no server / fetch / CORS needed).

Run:

    python ontology/export_web_graph.py            # uses latest artifact
    python ontology/export_web_graph.py --artifact <path> --instances 4
'''
import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit('PyYAML is required (it ships in the ontology uv sidecar env).')

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
SCHEMA_PATH = _HERE / 'schema' / 'v001.yaml'
EXTRACTIONS_DIR = _HERE / 'artifacts' / 'extractions'
RUNS_DIR = _HERE / 'artifacts' / 'runs'
EVAL_PATH = _HERE / 'results' / 'consolidation-eval.json'
OUT_PATH = _REPO / 'apps' / 'web' / 'app' / 'ontology' / 'graph-data.json'

_DISCOVERED_RE = re.compile(r'discovered in (\d+) narratives')


def latest_artifact() -> Path:
    cands = sorted(EXTRACTIONS_DIR.glob('extract-*.jsonl'))
    if not cands:
        sys.exit(f'No extraction artifacts under {EXTRACTIONS_DIR}.')
    return cands[-1]


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _discovered_count(description: str) -> int:
    m = _DISCOVERED_RE.search(description or '')
    return int(m.group(1)) if m else 0


# ---------------------------------------------------------------------------
# Schema meta-graph
# ---------------------------------------------------------------------------
def build_schema_graph(schema: dict) -> dict:
    '''Nodes = node types (colored by provenance, sized by discovery count),
    edges = the connection patterns (deduped, labeled by relationship type).'''
    rel_desc = {r['label']: r.get('description', '')
                for r in schema.get('relationship_types', [])}

    nodes = []
    for nt in schema.get('node_types', []):
        label = nt['label']
        prov = nt.get('provenance', 'narrative')
        count = _discovered_count(nt.get('description', ''))
        props = [p['name'] for p in nt.get('properties', []) or []]
        nodes.append({
            'id': label,
            'label': label,
            'group': prov,
            'value': 6 + count,            # base size + narrative frequency
            'discovered': count,
            'description': nt.get('description', ''),
            'properties': props,
        })

    seen = set()
    edges = []
    for pat in schema.get('patterns', []):
        if not (isinstance(pat, list) and len(pat) == 3):
            continue
        src, rel, dst = pat
        key = (src, rel, dst)
        if key in seen:
            continue
        seen.add(key)
        edges.append({
            'from': src,
            'to': dst,
            'label': rel,
            'title': f'{src} —{rel}→ {dst}\n{rel_desc.get(rel, "")}',
        })

    return {
        'nodes': nodes,
        'edges': edges,
        'competency_questions': schema.get('competency_questions', []),
        'counts': {
            'node_types': len(nodes),
            'relationship_types': len(schema.get('relationship_types', [])),
            'patterns': len(edges),
        },
    }


# ---------------------------------------------------------------------------
# Instance graphs (a few real incidents)
# ---------------------------------------------------------------------------
def _label_for(entity: dict) -> str:
    name = (entity.get('name') or entity.get('key') or '').strip()
    if len(name) > 32:
        name = name[:29] + '…'
    return name or entity.get('type', '?')


def build_instance_graph(rec: dict) -> dict:
    keys = {e['key'] for e in rec.get('entities', [])}
    nodes = []
    seen_keys: set[str] = set()
    for e in rec.get('entities', []):
        # Neo4j MERGEs on key; mirror that here so duplicate keys collapse to
        # one node (a vis DataSet rejects duplicate ids outright).
        if e['key'] in seen_keys:
            continue
        seen_keys.add(e['key'])
        props = e.get('properties') or {}
        prop_lines = '\n'.join(f'  {k}: {v}' for k, v in props.items())
        nodes.append({
            'id': e['key'],
            'label': _label_for(e),
            'group': e.get('provenance', 'narrative'),
            'value': 10,
            'type': e.get('type', '?'),
            'name': e.get('name', ''),
            'quote': e.get('quote', ''),
            'title': f'{e.get("type", "?")}: {e.get("name", "")}\n{prop_lines}'.strip(),
        })
    edges = []
    seen_edges: set[tuple] = set()
    for r in rec.get('relationships', []):
        # graph_load drops dangling rels; mirror that so the page matches the DB.
        if r.get('source_key') not in keys or r.get('target_key') not in keys:
            continue
        ekey = (r['source_key'], r['target_key'], r['type'])
        if ekey in seen_edges:                 # MERGE collapses parallel rels
            continue
        seen_edges.add(ekey)
        edges.append({
            'from': r['source_key'],
            'to': r['target_key'],
            'label': r['type'],
            'title': r.get('quote', '') or r['type'],
        })
    return {
        'doc_key': rec['doc_key'],
        'nodes': nodes,
        'edges': edges,
    }


def select_instances(records: list[dict], n: int,
                     lo: int = 10, hi: int = 26) -> list[dict]:
    '''Pick a handful of legible incidents that read clearly (not a hairball):
    status ok, with some narrative discovery, sampled across the size band so
    the examples vary in shape rather than all being the densest.'''
    scored = []
    for r in records:
        if r.get('status') != 'ok':
            continue
        ents = r.get('entities', [])
        n_ent = len(ents)
        n_nar = sum(1 for e in ents if e.get('provenance') == 'narrative')
        if not (lo <= n_ent <= hi) or n_nar == 0:
            continue
        scored.append((n_ent, r))
    scored.sort(key=lambda t: t[0])               # smallest -> largest
    if len(scored) <= n:
        picks = [r for _, r in scored]
    else:                                          # evenly spaced across sizes
        step = (len(scored) - 1) / (n - 1)
        picks = [scored[round(i * step)][1] for i in range(n)]
    return [build_instance_graph(r) for r in picks]


# ---------------------------------------------------------------------------
# Headline stats
# ---------------------------------------------------------------------------
def build_stats(artifact: Path) -> dict:
    stats: dict = {'artifact': artifact.name}
    summary = RUNS_DIR / f'{artifact.stem}.summary.json'
    if summary.exists():
        s = json.loads(summary.read_text(encoding='utf-8'))
        stats['run'] = {
            'model_id': s.get('model_id'),
            'docs_recorded': s.get('docs_recorded'),
            'statuses': s.get('statuses', {}),
            'counters': s.get('counters', {}),
            'llm_stats': s.get('llm_stats', {}),
            'n_canonical_rows': s.get('data_snapshot', {}).get('n_canonical_rows'),
        }
    if EVAL_PATH.exists():
        e = json.loads(EVAL_PATH.read_text(encoding='utf-8'))
        stats['consolidation'] = e.get('metrics', {})
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--artifact', type=Path, default=None,
                    help='extraction JSONL (default: latest under artifacts/extractions)')
    ap.add_argument('--instances', type=int, default=4,
                    help='how many example incidents to include (default 4)')
    ap.add_argument('--out', type=Path, default=OUT_PATH)
    args = ap.parse_args()

    artifact = args.artifact or latest_artifact()
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding='utf-8'))
    records = load_jsonl(artifact)

    payload = {
        '_comment': ('Generated by ontology/export_web_graph.py - do not edit by '
                     'hand. Rebuild after a pipeline run: '
                     'python ontology/export_web_graph.py'),
        'generated_from': {
            'schema': SCHEMA_PATH.name,
            'schema_version': schema.get('version'),
            'artifact': artifact.name,
        },
        'schema': build_schema_graph(schema),
        'instances': select_instances(records, args.instances),
        'stats': build_stats(artifact),
    }

    # Plain JSON imported directly by the Next.js /ontology route (server
    # component), not a window global. Static reference data — it does not flow
    # through the DB-backed apps/api service.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')

    n_inst = len(payload['instances'])
    sc = payload['schema']['counts']
    print(f'Wrote {args.out}')
    print(f'  schema:    {sc["node_types"]} node types, '
          f'{sc["relationship_types"]} rel types, {sc["patterns"]} patterns')
    print(f'  instances: {n_inst} incidents from {artifact.name}')


if __name__ == '__main__':
    main()
