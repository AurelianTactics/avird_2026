'''Golden dataset tooling: stratified sampling, pre-labeling, staleness.

The golden set is 40-50 human-corrected narratives with versioned annotation
guidelines (``golden/guidelines.md``) and a disciplined split: ~10 dev docs
for prompt iteration, ~30+ held-out docs touched only for final numbers
(``evaluate.py`` refuses held-out without ``--heldout``).

Workflow:

1. ``python ontology/golden.py sample`` — stratified sample (narrative
   length × master_entity × ADS/ADAS; redacted docs excluded except 2-3 kept
   deliberately to exercise the skip path), pre-labeled with a Sonnet-class
   model (stronger and *different* from the pipeline model), written as
   ``golden/dev.jsonl`` + ``golden/heldout.jsonl``.
2. Human corrects every annotation by hand-editing the JSONL (no annotation
   UI — deliberate YAGNI). ``UNMAPPED`` is a legal entity type for salient
   mentions no schema type expresses; add a free-text ``candidate_type``.
3. Records pin ``text_sha256`` of the preprocessed text, so corpus refreshes
   surface as loud staleness warnings rather than silent drift.

Golden records reuse the extraction artifact's per-doc shape so eval compares
like with like.
'''
import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from llm import CachedLLM, GOLDEN_PRELABEL_MODEL_ID  # noqa: E402

GOLDEN_DIR = _HERE / 'golden'
DEFAULT_N = 45
DEFAULT_DEV_SIZE = 10
DEFAULT_REDACTED_KEPT = 2
GUIDELINES_VERSION = 'v0.1'
UNMAPPED = 'UNMAPPED'


# ---------------------------------------------------------------------------
# Stratified sampling
# ---------------------------------------------------------------------------
def length_bucket_thresholds(docs):
    lengths = sorted(len(d.text) for d in docs)
    if not lengths:
        return (0, 0)
    return (lengths[len(lengths) // 3], lengths[2 * len(lengths) // 3])


def stratum_key(doc, thresholds):
    lo, hi = thresholds
    n = len(doc.text)
    bucket = 'short' if n <= lo else ('medium' if n <= hi else 'long')
    # NOTE: redaction concentrates in specific entities, so entity strata are
    # coarse buckets, not per-entity quotas (naive per-entity stratification
    # would produce unlabelable strata).
    entity = doc.row.get('master_entity') or 'unknown'
    automation = doc.row.get('automation_system_type') or 'Unknown'
    return (entity, automation, bucket)


def stratified_sample(docs, n=DEFAULT_N, seed=0,
                      include_redacted=DEFAULT_REDACTED_KEPT):
    '''Seeded, deterministic sample. Returns (sampled docs, strata report).'''
    eligible = sorted((d for d in docs if not d.skip_reason and d.text),
                      key=lambda d: d.doc_key)
    redacted = sorted((d for d in docs if d.skip_reason == 'skipped_redacted'),
                      key=lambda d: d.doc_key)
    rng = random.Random(seed)
    thresholds = length_bucket_thresholds(eligible)

    strata = {}
    for d in eligible:
        strata.setdefault(stratum_key(d, thresholds), []).append(d)

    n_eligible_target = max(n - min(include_redacted, len(redacted)), 0)
    sampled = []
    if len(eligible) <= n_eligible_target:
        sampled = list(eligible)
    else:
        keys = sorted(strata, key=lambda k: (-len(strata[k]), k))
        remaining = n_eligible_target
        quotas = {}
        for key in keys:
            if remaining <= 0:
                break
            share = max(1, round(n_eligible_target * len(strata[key])
                                 / len(eligible)))
            quotas[key] = min(share, len(strata[key]), remaining)
            remaining -= quotas[key]
        for key, quota in quotas.items():
            sampled.extend(rng.sample(strata[key], quota))

    kept_redacted = rng.sample(redacted, min(include_redacted, len(redacted)))
    sampled = sorted(sampled + kept_redacted, key=lambda d: d.doc_key)
    report = {
        'n_sampled': len(sampled),
        'n_redacted_kept': len(kept_redacted),
        'strata': {str(k): len(v) for k, v in sorted(strata.items())},
    }
    return sampled, report


def split_dev_heldout(docs, dev_size=DEFAULT_DEV_SIZE, seed=0):
    '''Disjoint, seeded, stable split. Returns (dev docs, heldout docs).'''
    ordered = sorted(docs, key=lambda d: d.doc_key)
    rng = random.Random(seed)
    rng.shuffle(ordered)
    return (sorted(ordered[:dev_size], key=lambda d: d.doc_key),
            sorted(ordered[dev_size:], key=lambda d: d.doc_key))


# ---------------------------------------------------------------------------
# Pre-labeling (Sonnet-class model; human corrects everything after)
# ---------------------------------------------------------------------------
def prelabel_doc(doc, schema, llm, split,
                 guidelines_version=GUIDELINES_VERSION):
    '''One golden record in the extraction artifact's per-doc shape.'''
    from extract import build_extraction_model, column_instances, \
        extraction_prompt
    from prune import prune_extraction

    entities, relationships, keyer = column_instances(doc)
    status = doc.skip_reason or 'ok'
    counters = {}
    if not doc.skip_reason:
        raw = llm.call(extraction_prompt(schema, doc.text),
                       build_extraction_model(schema))
        if raw is None:
            status = 'dry_run_miss'
        else:
            pruned = prune_extraction(schema, raw, doc.text, doc.doc_key,
                                      keyer=keyer)
            counters = pruned.counters
            entities.extend(pruned.entities)
            relationships.extend(pruned.relationships)
    return {
        'doc_key': doc.doc_key,
        'split': split,
        'guidelines_version': guidelines_version,
        'status': status,
        'text_sha256': doc.text_sha256,
        'text': doc.text,
        'entities': [asdict(e) for e in entities],
        'relationships': [asdict(r) for r in relationships],
        'prelabel_counters': counters,
    }


# ---------------------------------------------------------------------------
# Record validation + staleness
# ---------------------------------------------------------------------------
def validate_golden_record(record, schema):
    '''Raise ValueError listing every problem in one pass.'''
    problems = []
    for field in ('doc_key', 'split', 'guidelines_version', 'text_sha256',
                  'entities', 'relationships'):
        if field not in record:
            problems.append(f'missing field {field!r}')
    labels = {n.label for n in schema.node_types} | {UNMAPPED}
    rel_labels = {r.label for r in schema.relationship_types}
    keys = set()
    for ent in record.get('entities', []):
        if ent.get('type') not in labels:
            problems.append(f'unknown entity type {ent.get("type")!r}')
        if ent.get('type') == UNMAPPED and not ent.get('candidate_type'):
            problems.append(f'UNMAPPED entity {ent.get("name")!r} needs a '
                            f'free-text candidate_type')
        if ent.get('key'):
            keys.add(ent['key'])
    for rel in record.get('relationships', []):
        if rel.get('type') not in rel_labels:
            problems.append(f'unknown relationship type {rel.get("type")!r}')
        for end in ('source_key', 'target_key'):
            if rel.get(end) not in keys:
                problems.append(f'relationship {rel.get("type")} {end} '
                                f'{rel.get(end)!r} matches no entity key')
    if problems:
        raise ValueError(f'golden record {record.get("doc_key")!r}: '
                         + '; '.join(problems))
    return True


def check_staleness(records, docs_by_key):
    '''Doc keys whose preprocessed text changed since annotation.'''
    stale = []
    for record in records:
        doc = docs_by_key.get(record['doc_key'])
        if doc is None:
            stale.append((record['doc_key'], 'missing from corpus'))
        elif doc.text_sha256 != record['text_sha256']:
            stale.append((record['doc_key'], 'text hash mismatch'))
    return stale


def load_golden(path, schema=None):
    records = [json.loads(line) for line in
               Path(path).read_text(encoding='utf-8').splitlines()
               if line.strip()]
    if schema is not None:
        for record in records:
            validate_golden_record(record, schema)
    return records


def annotation_counts(records):
    return {
        'docs': len(records),
        'entities': sum(len(r['entities']) for r in records),
        'relationships': sum(len(r['relationships']) for r in records),
    }


def write_jsonl(records, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as f:
        for record in records:
            f.write(json.dumps(record, default=str) + '\n')
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest='command', required=True)

    sample = sub.add_parser('sample',
                            help='Stratified sample + Sonnet pre-label -> '
                                 'golden/dev.jsonl + golden/heldout.jsonl.')
    sample.add_argument('--schema', required=True,
                        help='Frozen schema path (drafts refused).')
    sample.add_argument('--n', type=int, default=DEFAULT_N)
    sample.add_argument('--dev-size', type=int, default=DEFAULT_DEV_SIZE)
    sample.add_argument('--seed', type=int, default=0)
    sample.add_argument('--dry-run', action='store_true')

    check = sub.add_parser('check', help='Validate + staleness-check golden '
                                         'files against the live corpus.')
    check.add_argument('--schema', required=True)

    args = p.parse_args(argv)
    from corpus import load_corpus
    from schema_model import load_frozen_schema
    schema = load_frozen_schema(args.schema)
    corpus = load_corpus()

    if args.command == 'sample':
        for name in ('dev.jsonl', 'heldout.jsonl'):
            if (GOLDEN_DIR / name).exists():
                print(f'refusing to overwrite existing {GOLDEN_DIR / name} - '
                      f'golden corrections are hand labor; move it first.',
                      file=sys.stderr)
                return 2
        sampled, report = stratified_sample(corpus.docs, n=args.n,
                                            seed=args.seed)
        dev, heldout = split_dev_heldout(sampled, dev_size=args.dev_size,
                                         seed=args.seed)
        llm = CachedLLM(model_id=GOLDEN_PRELABEL_MODEL_ID,
                        dry_run=args.dry_run)
        print(f'sampled {report["n_sampled"]} docs '
              f'({report["n_redacted_kept"]} redacted kept), '
              f'{len(dev)} dev / {len(heldout)} heldout')
        if args.dry_run:
            print(f'--dry-run: would pre-label with {llm.model_id}. Exit 0.')
            return 0
        dev_records = [prelabel_doc(d, schema, llm, 'dev') for d in dev]
        heldout_records = [prelabel_doc(d, schema, llm, 'heldout')
                           for d in heldout]
        write_jsonl(dev_records, GOLDEN_DIR / 'dev.jsonl')
        write_jsonl(heldout_records, GOLDEN_DIR / 'heldout.jsonl')
        print(f'llm stats: {llm.stats}')
        print(f'pre-label counts: '
              f'{annotation_counts(dev_records + heldout_records)}')
        print('next: hand-correct every annotation in dev.jsonl/heldout.jsonl '
              '(see golden/guidelines.md), then re-run `golden.py check`.')
        return 0

    if args.command == 'check':
        docs_by_key = {d.doc_key: d for d in corpus.docs}
        for name in ('dev.jsonl', 'heldout.jsonl'):
            path = GOLDEN_DIR / name
            if not path.exists():
                print(f'{name}: missing')
                continue
            records = load_golden(path, schema=schema)
            stale = check_staleness(records, docs_by_key)
            counts = annotation_counts(records)
            print(f'{name}: {counts}')
            for doc_key, reason in stale:
                print(f'  STALE {doc_key}: {reason}', file=sys.stderr)
            if stale:
                return 1
        return 0
    return 2  # pragma: no cover


if __name__ == '__main__':
    sys.exit(main())
