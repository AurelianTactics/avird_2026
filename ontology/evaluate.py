'''Per-stage metrics from durable artifacts; committed summaries back claims.

Three evaluation surfaces, each runnable independently:

- **extraction** — artifact vs golden, per doc, scored over ``provenance:
  narrative`` instances only (deterministic column entities can't distort the
  numbers). Entity + relationship P/R/F1 under strict matching (type +
  normalized name/quote + direction) and relaxed (type + fuzzy span overlap);
  hallucination / quote-mismatch rates from the validation counters;
  omission (golden items with no prediction); direction-error rate from the
  artifact's as-emitted vs corrected fields; a detection-vs-typing component
  breakdown so failures are localizable; golden-mention coverage =
  mapped / (mapped + UNMAPPED).
- **consolidation** — pairwise same-group P/R/F1 of the LLM's proposed merge
  groups against ``golden/consolidation.jsonl`` (R16).
- **graph** — re-runnable Cypher assertions against AuraDB: orphan rate,
  required-property presence, undeclared labels, cardinality spot checks,
  competency-question answerability.

Held-out hygiene: the held-out split is final-numbers-only; loading it
requires the explicit ``--heldout`` flag (AE4).

Summaries (JSON + a short markdown table) are deterministic for fixed inputs
and are committed to ``ontology/results/``; raw run records stay gitignored.
'''
import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from prune import normalize_name  # noqa: E402

GOLDEN_DIR = _HERE / 'golden'
RESULTS_DIR = _HERE / 'results'
UNMAPPED = 'UNMAPPED'
FUZZY_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_jsonl(path):
    return [json.loads(line) for line in
            Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def golden_split_path(split, allow_heldout=False, golden_dir=GOLDEN_DIR):
    '''The held-out split is refused without the explicit flag (AE4).'''
    if split == 'heldout' and not allow_heldout:
        raise PermissionError(
            'refusing to read heldout.jsonl without --heldout. The held-out '
            'split is for final numbers only; iterate against dev.')
    return Path(golden_dir) / f'{split}.jsonl'


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
def fuzzy_overlap(a, b, threshold=FUZZY_THRESHOLD):
    '''Deterministic span similarity over normalized text.'''
    na, nb = normalize_name(a or ''), normalize_name(b or '')
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb, autojunk=False).ratio() >= threshold


def entity_match(gold, pred, mode):
    if mode == 'strict':
        return gold['type'] == pred['type'] and (
            normalize_name(gold['name']) == normalize_name(pred['name'])
            or (normalize_name(gold.get('quote', ''))
                == normalize_name(pred.get('quote', '')) != ''))
    return gold['type'] == pred['type'] and (
        fuzzy_overlap(gold['name'], pred['name'])
        or fuzzy_overlap(gold.get('quote', ''), pred.get('quote', '')))


def detection_match(gold, pred):
    '''Type-agnostic: did extraction find this mention at all?'''
    return (fuzzy_overlap(gold['name'], pred['name'])
            or fuzzy_overlap(gold.get('quote', ''), pred.get('quote', '')))


def greedy_match(golds, preds, match_fn):
    '''One-to-one greedy matching, deterministic given input order.

    Returns a list of (gold index, pred index) pairs.
    '''
    matched_preds = set()
    pairs = []
    for gi, gold in enumerate(golds):
        for pi, pred in enumerate(preds):
            if pi in matched_preds:
                continue
            if match_fn(gold, pred):
                pairs.append((gi, pi))
                matched_preds.add(pi)
                break
    return pairs


def prf(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if precision + recall else 0.0)
    return {'tp': tp, 'fp': fp, 'fn': fn,
            'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1': round(f1, 4)}


def narrative_only(instances):
    return [x for x in instances if x.get('provenance') == 'narrative']


def mappable(entities):
    return [e for e in entities if e.get('type') != UNMAPPED]


# ---------------------------------------------------------------------------
# Extraction eval
# ---------------------------------------------------------------------------
def evaluate_extraction(golden_records, artifact_records):
    preds_by_key = {r['doc_key']: r for r in artifact_records}
    missing = [g['doc_key'] for g in golden_records
               if g['doc_key'] not in preds_by_key]
    if missing:
        raise ValueError(
            f'artifact lacks golden docs {missing[:5]} - re-run extraction '
            f'with --include-golden')

    counts = {mode: {'entities': [0, 0, 0], 'relationships': [0, 0, 0]}
              for mode in ('strict', 'relaxed')}   # [tp, fp, fn]
    detected = 0
    typed_correctly = 0
    golden_mentions = {'mapped': 0, 'unmapped': 0}
    counters_total = {}
    rel_total = 0
    rel_corrected = 0

    for gold_record in golden_records:
        pred_record = preds_by_key[gold_record['doc_key']]
        gold_ents_all = narrative_only(gold_record['entities'])
        gold_ents = mappable(gold_ents_all)
        gold_rels = narrative_only(gold_record['relationships'])
        pred_ents = narrative_only(pred_record['entities'])
        pred_rels = narrative_only(pred_record['relationships'])

        golden_mentions['mapped'] += len(gold_ents)
        golden_mentions['unmapped'] += len(gold_ents_all) - len(gold_ents)

        for name, total in (pred_record.get('counters') or {}).items():
            counters_total[name] = counters_total.get(name, 0) + total
        rel_total += len(pred_rels)
        rel_corrected += sum(1 for r in pred_rels if r.get('direction_corrected'))

        for mode in ('strict', 'relaxed'):
            ent_pairs = greedy_match(gold_ents, pred_ents,
                                     lambda g, p: entity_match(g, p, mode))
            tp = len(ent_pairs)
            counts[mode]['entities'][0] += tp
            counts[mode]['entities'][1] += len(pred_ents) - tp
            counts[mode]['entities'][2] += len(gold_ents) - tp

            # Relationship matching rides on the entity key mapping.
            key_map = {gold_ents[gi]['key']: pred_ents[pi]['key']
                       for gi, pi in ent_pairs}

            def rel_match(g, p):
                return (g['type'] == p['type']
                        and key_map.get(g['source_key']) == p['source_key']
                        and key_map.get(g['target_key']) == p['target_key'])

            rel_pairs = greedy_match(gold_rels, pred_rels, rel_match)
            rtp = len(rel_pairs)
            counts[mode]['relationships'][0] += rtp
            counts[mode]['relationships'][1] += len(pred_rels) - rtp
            counts[mode]['relationships'][2] += len(gold_rels) - rtp

        det_pairs = greedy_match(gold_ents, pred_ents, detection_match)
        detected += len(det_pairs)
        typed_correctly += sum(
            1 for gi, pi in det_pairs
            if gold_ents[gi]['type'] == pred_ents[pi]['type'])

    total_gold_ents = sum(counts['strict']['entities'][0:3:2])  # tp + fn
    halluc = counters_total.get('hallucination', 0)
    mismatch = counters_total.get('quote_mismatch', 0)
    attempted = (sum(len(narrative_only(preds_by_key[g['doc_key']]['entities']))
                     + len(narrative_only(preds_by_key[g['doc_key']]['relationships']))
                     for g in golden_records) + halluc + mismatch)

    mapped, unmapped = golden_mentions['mapped'], golden_mentions['unmapped']
    return {
        'docs_scored': len(golden_records),
        'entities': {m: prf(*counts[m]['entities']) for m in counts},
        'relationships': {m: prf(*counts[m]['relationships']) for m in counts},
        'rates': {
            'hallucination_count': halluc,
            'quote_mismatch_count': mismatch,
            'hallucination_rate': round(halluc / attempted, 4) if attempted else 0.0,
            'quote_mismatch_rate': round(mismatch / attempted, 4) if attempted else 0.0,
            'direction_error_rate': round(rel_corrected / rel_total, 4) if rel_total else 0.0,
            'direction_corrected_count': rel_corrected,
            'omission_strict': counts['strict']['entities'][2],
            'omission_relaxed': counts['relaxed']['entities'][2],
            'omission_rate_strict': round(
                counts['strict']['entities'][2] / total_gold_ents, 4)
                if total_gold_ents else 0.0,
        },
        'components': {
            'detection_recall': round(detected / total_gold_ents, 4)
                                if total_gold_ents else 0.0,
            'typing_accuracy': round(typed_correctly / detected, 4)
                               if detected else 0.0,
        },
        'coverage': {
            'mapped': mapped,
            'unmapped': unmapped,
            'coverage': round(mapped / (mapped + unmapped), 4)
                        if mapped + unmapped else 0.0,
        },
        'validation_counters': dict(sorted(counters_total.items())),
    }


# ---------------------------------------------------------------------------
# Consolidation eval (R16)
# ---------------------------------------------------------------------------
def pairwise_pairs(groups):
    '''Unordered same-group member pairs, per kind, names normalized.'''
    pairs = set()
    for group in groups:
        members = sorted({normalize_name(m) for m in group['members']})
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                pairs.add((group['kind'], a, b))
    return pairs


def evaluate_consolidation(proposed_groups, golden_groups):
    pred = pairwise_pairs(proposed_groups)
    gold = pairwise_pairs(golden_groups)
    tp = len(pred & gold)
    metrics = prf(tp, len(pred - gold), len(gold - pred))
    return {'pairwise': metrics,
            'proposed_groups': len(proposed_groups),
            'golden_groups': len(golden_groups)}


def approval_diff(draft_schema, approved_schema):
    '''Types added/dropped/renamed between draft and approved schema.'''
    def labels(schema, attr):
        return {t.label for t in getattr(schema, attr)}
    diff = {}
    for attr in ('node_types', 'relationship_types'):
        draft, approved = labels(draft_schema, attr), labels(approved_schema, attr)
        diff[attr] = {'added': sorted(approved - draft),
                      'dropped': sorted(draft - approved)}
    return diff


# ---------------------------------------------------------------------------
# Graph assertions
# ---------------------------------------------------------------------------
def graph_assertion_queries(schema):
    '''(name, cypher) pairs; every count query aliases its scalar as ``n``.'''
    queries = [
        ('node_count', 'MATCH (n) RETURN count(n) AS n'),
        ('relationship_count', 'MATCH ()-[r]->() RETURN count(r) AS n'),
        ('orphan_nodes', 'MATCH (n) WHERE NOT (n)--() RETURN count(n) AS n'),
    ]
    for node in schema.node_types:
        for spec in node.properties:
            if spec.required:
                queries.append((
                    f'missing_required_{node.label}_{spec.name}',
                    f'MATCH (n:`{node.label}`) WHERE n.`{spec.name}` IS NULL '
                    f'RETURN count(n) AS n'))
    if {'Incident', 'Vehicle'} <= {n.label for n in schema.node_types}:
        queries.append((
            'incident_without_vehicle',
            'MATCH (i:Incident) WHERE NOT (i)-[:INVOLVES]->(:Vehicle) '
            'RETURN count(i) AS n'))
    return queries


def run_graph_assertions(driver, schema):
    results = {}
    for name, query in graph_assertion_queries(schema):
        records = list(driver.execute_query(query).records)
        results[name] = records[0]['n'] if records else 0
    nodes = results.get('node_count', 0)
    results['orphan_rate'] = (round(results.get('orphan_nodes', 0) / nodes, 4)
                              if nodes else 0.0)

    label_result = driver.execute_query(
        'CALL db.labels() YIELD label RETURN collect(label) AS labels')
    records = list(label_result.records)
    graph_labels = set(records[0]['labels']) if records else set()
    declared = {n.label for n in schema.node_types}
    results['undeclared_labels'] = sorted(graph_labels - declared)
    return results


def evaluate_competency_questions(driver, schema, queries_map):
    '''Answerability: each CQ has a Cypher query that runs and returns rows.

    ``queries_map`` is {question: cypher}, hand-maintained; the plausibility
    judgment stays a hand-checked binary recorded alongside the summary.
    '''
    per_question = []
    for question in schema.competency_questions:
        cypher = queries_map.get(question)
        entry = {'question': question, 'has_query': cypher is not None,
                 'returned_rows': None}
        if cypher:
            records = list(driver.execute_query(cypher).records)
            entry['returned_rows'] = len(records)
        per_question.append(entry)
    answerable = sum(1 for e in per_question
                     if e['has_query'] and (e['returned_rows'] or 0) > 0)
    total = len(per_question)
    return {'questions': per_question,
            'answerable': answerable,
            'total': total,
            'answerability': round(answerable / total, 4) if total else 0.0}


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------
def _flatten(metrics, prefix=''):
    rows = []
    for key in sorted(metrics):
        value = metrics[key]
        name = f'{prefix}{key}'
        if isinstance(value, dict):
            rows.extend(_flatten(value, prefix=f'{name}.'))
        elif not isinstance(value, list):
            rows.append((name, value))
    return rows


def write_summary(metrics, name, out_dir=RESULTS_DIR, inputs=None):
    '''Deterministic JSON + markdown table for fixed inputs.'''
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {'name': name, 'inputs': inputs or {}, 'metrics': metrics}
    json_path = out_dir / f'{name}.json'
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True),
                         encoding='utf-8', newline='\n')
    lines = [f'# {name}', '', '| metric | value |', '|---|---|']
    lines += [f'| {key} | {value} |' for key, value in _flatten(metrics)]
    md_path = out_dir / f'{name}.md'
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8',
                       newline='\n')
    return json_path, md_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)

    ext = sub.add_parser('extraction', help='Artifact vs golden metrics.')
    ext.add_argument('--artifact', required=True)
    ext.add_argument('--heldout', action='store_true',
                     help='Score the held-out split (final numbers only).')
    ext.add_argument('--out-name', default=None)

    cons = sub.add_parser('consolidation',
                          help='Merge-group pairwise P/R/F1 (R16).')
    cons.add_argument('--proposed', required=True,
                      help='LLM-proposed merge groups JSONL.')
    cons.add_argument('--golden',
                      default=str(GOLDEN_DIR / 'consolidation.jsonl'))
    cons.add_argument('--out-name', default='consolidation-eval')

    graph = sub.add_parser('graph', help='Cypher assertions against AuraDB.')
    graph.add_argument('--schema', required=True)
    graph.add_argument('--cq-queries', default=None,
                       help='YAML file mapping competency question -> Cypher.')
    graph.add_argument('--out-name', default='graph-eval')

    args = p.parse_args(argv)

    if args.command == 'extraction':
        split = 'heldout' if args.heldout else 'dev'
        golden = load_jsonl(golden_split_path(split,
                                              allow_heldout=args.heldout))
        artifact = load_jsonl(args.artifact)
        metrics = evaluate_extraction(golden, artifact)
        name = args.out_name or f'extraction-eval-{split}'
        paths = write_summary(metrics, name,
                              inputs={'artifact': Path(args.artifact).name,
                                      'split': split,
                                      'golden_docs': len(golden)})
        print(f'entities strict F1:  {metrics["entities"]["strict"]["f1"]}')
        print(f'entities relaxed F1: {metrics["entities"]["relaxed"]["f1"]}')
        print(f'summary: {paths[0]}')
        return 0

    if args.command == 'consolidation':
        metrics = evaluate_consolidation(load_jsonl(args.proposed),
                                         load_jsonl(args.golden))
        paths = write_summary(metrics, args.out_name,
                              inputs={'proposed': Path(args.proposed).name,
                                      'golden': Path(args.golden).name})
        print(f'pairwise F1: {metrics["pairwise"]["f1"]}')
        print(f'summary: {paths[0]}')
        return 0

    if args.command == 'graph':
        from graph_load import get_driver, preflight
        from schema_model import load_frozen_schema
        schema = load_frozen_schema(args.schema)
        queries_map = {}
        if args.cq_queries:
            import yaml
            queries_map = yaml.safe_load(
                Path(args.cq_queries).read_text(encoding='utf-8')) or {}
        driver = get_driver()
        try:
            preflight(driver)
            metrics = run_graph_assertions(driver, schema)
            metrics['competency_questions'] = evaluate_competency_questions(
                driver, schema, queries_map)
        finally:
            driver.close()
        paths = write_summary(metrics, args.out_name,
                              inputs={'schema': schema.version})
        print(f'orphan rate: {metrics["orphan_rate"]}')
        print(f'summary: {paths[0]}')
        return 0
    return 2  # pragma: no cover


if __name__ == '__main__':
    sys.exit(main())
