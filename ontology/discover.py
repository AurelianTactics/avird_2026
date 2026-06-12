'''LangGraph graph 1: LLM concept discovery + schema consolidation.

Pipeline: stratified narrative sample → per-narrative concept discovery
(structured output, cached) → deterministic aggregation → one LLM
consolidation pass proposing synonym merge groups → draft schema merging the
deterministic seed (provenance ``column``) with discovered types (provenance
``narrative``).

Outputs (both committed for review history):

- ``ontology/schema/drafts/v001-draft.yaml`` — the reviewable draft. The
  human edits it, adds competency questions, saves as
  ``ontology/schema/v001.yaml``, and commits. Extraction refuses drafts.
- ``ontology/schema/drafts/v001-draft-merge-groups.jsonl`` — the LLM's
  proposed merge groups. The same approval pass corrects them into
  ``ontology/golden/consolidation.jsonl`` (the consolidation golden, R16).

Run from the repo root (needs ``DATABASE_URL`` + ``ANTHROPIC_API_KEY``)::

    python ontology/discover.py --dry-run        # count cache misses first
    python ontology/discover.py --sample 300
'''
import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Literal, Optional, TypedDict

from pydantic import BaseModel, ConfigDict, Field

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from llm import CachedLLM  # noqa: E402
from schema_model import (  # noqa: E402
    NodeType,
    OntologySchema,
    RelationshipType,
    dump_schema,
)
from seed_schema import build_seed_schema  # noqa: E402

DRAFTS_DIR = _HERE / 'schema' / 'drafts'
DEFAULT_DRAFT_PATH = DRAFTS_DIR / 'v001-draft.yaml'
DEFAULT_MERGE_GROUPS_PATH = DRAFTS_DIR / 'v001-draft-merge-groups.jsonl'

DEFAULT_SAMPLE_SIZE = 300
DEFAULT_MIN_SUPPORT = 2


# ---------------------------------------------------------------------------
# Structured-output models (kept flat per the plan's quality guidance)
# ---------------------------------------------------------------------------
class CandidateNodeType(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    description: str = ''
    example_mention: str = ''


class CandidateRelationshipType(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str
    source: str
    target: str
    description: str = ''
    example_mention: str = ''


class NarrativeConcepts(BaseModel):
    model_config = ConfigDict(extra='forbid')
    node_types: list[CandidateNodeType] = Field(default_factory=list)
    relationship_types: list[CandidateRelationshipType] = Field(default_factory=list)


class MergeGroup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['node', 'relationship']
    canonical_name: str
    description: str = ''
    members: list[str] = Field(default_factory=list)


class ConsolidationProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    groups: list[MergeGroup] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------
def discovery_prompt(text, seed_labels):
    return (
        'You are building a property-graph ontology over autonomous-vehicle '
        'crash narratives.\n'
        f'These entity types are already covered by structured data, do NOT '
        f'propose them: {", ".join(sorted(seed_labels))}.\n'
        'Read the narrative and propose entity types and relationship types '
        'that the narrative expresses but the list above does not. Propose '
        'general, reusable types (e.g. Pedestrian, TrafficControl), not '
        'instances. For each, quote a short example mention from the '
        'narrative. Return nothing when the narrative adds no new types.\n\n'
        f'Narrative:\n{text}'
    )


def consolidation_prompt(candidate_summary):
    return (
        'You are consolidating candidate ontology types proposed across many '
        'crash narratives. Group together candidates that mean the same '
        'concept (synonyms, plurals, spelling variants). Only group true '
        'synonyms - do not merge distinct concepts. Every group lists its '
        'member candidate names exactly as given; candidates that have no '
        'synonym should not appear in any group.\n\n'
        f'Candidates:\n{candidate_summary}'
    )


# ---------------------------------------------------------------------------
# Deterministic helpers
# ---------------------------------------------------------------------------
def _norm_key(name):
    return re.sub(r'[^a-z0-9]+', ' ', str(name).lower()).strip()


def node_label_from_key(key):
    return ''.join(w.capitalize() for w in key.split())


def rel_label_from_key(key):
    return '_'.join(w.upper() for w in key.split())


def sample_narratives(docs, n=DEFAULT_SAMPLE_SIZE, seed=0):
    '''Stratified-by-master_entity, seeded, deterministic sample.

    Non-skipped docs only. Allocation is proportional to entity volume with
    every entity keeping at least one doc while n allows.
    '''
    eligible = [d for d in docs if not d.skip_reason and d.text]
    if len(eligible) <= n:
        return eligible
    by_entity = defaultdict(list)
    for d in eligible:
        by_entity[d.row.get('master_entity', 'unknown')].append(d)
    for group in by_entity.values():
        group.sort(key=lambda d: d.doc_key)

    entities = sorted(by_entity, key=lambda e: (-len(by_entity[e]), e))
    rng = random.Random(seed)
    quotas = {}
    remaining = n
    for i, entity in enumerate(entities):
        share = max(1, round(n * len(by_entity[entity]) / len(eligible)))
        quota = min(share, len(by_entity[entity]), remaining)
        quotas[entity] = quota
        remaining -= quota
        if remaining <= 0:
            break
    sampled = []
    for entity, quota in quotas.items():
        sampled.extend(rng.sample(by_entity[entity], quota))
    return sorted(sampled, key=lambda d: d.doc_key)


def _new_concept_info():
    return {'names': defaultdict(int), 'doc_keys': set(), 'descriptions': [],
            'examples': [], 'endpoints': defaultdict(int)}


def aggregate_concepts(per_doc):
    '''Merge per-doc candidates into {kind: {norm_key: info}} with counts.'''
    agg = {'node': {}, 'relationship': {}}

    def add(kind, name, doc_key, description, example, source=None, target=None):
        key = _norm_key(name)
        if not key:
            return
        info = agg[kind].setdefault(key, _new_concept_info())
        info['names'][name.strip()] += 1
        info['doc_keys'].add(doc_key)
        if description:
            info['descriptions'].append(description)
        if example:
            info['examples'].append(example)
        if source and target:
            info['endpoints'][(_norm_key(source), _norm_key(target))] += 1

    for doc_key, concepts in per_doc:
        if concepts is None:
            continue
        for c in concepts.node_types:
            add('node', c.name, doc_key, c.description, c.example_mention)
        for c in concepts.relationship_types:
            add('relationship', c.name, doc_key, c.description,
                c.example_mention, c.source, c.target)
    return agg


def candidate_summary(agg):
    '''Render the aggregate for the consolidation prompt, deterministically.'''
    lines = []
    for kind in ('node', 'relationship'):
        for key in sorted(agg[kind]):
            info = agg[kind][key]
            display = max(sorted(info['names']), key=lambda n: info['names'][n])
            lines.append(f'{kind}: {display} '
                         f'(seen in {len(info["doc_keys"])} narratives)')
    return '\n'.join(lines)


def apply_merge_groups(agg, proposal):
    '''Fold synonym members into canonical keys. Deterministic given inputs.'''
    if proposal is None:
        return agg
    mapping = {'node': {}, 'relationship': {}}
    for group in proposal.groups:
        canon = _norm_key(group.canonical_name)
        for member in group.members:
            mapping[group.kind][_norm_key(member)] = canon

    merged = {'node': {}, 'relationship': {}}
    for kind in ('node', 'relationship'):
        for key in sorted(agg[kind]):
            target_key = mapping[kind].get(key, key)
            info = agg[kind][key]
            out = merged[kind].setdefault(target_key, _new_concept_info())
            for name, count in info['names'].items():
                out['names'][name] += count
            out['doc_keys'] |= info['doc_keys']
            out['descriptions'].extend(info['descriptions'])
            out['examples'].extend(info['examples'])
            for ep, count in info['endpoints'].items():
                out['endpoints'][ep] += count
    return merged


def build_draft_schema(seed, agg, version='v001-draft',
                       min_support=DEFAULT_MIN_SUPPORT):
    '''Merge seed (column provenance) + discovered (narrative provenance).'''
    seed_node_keys = {_norm_key(n.label): n.label for n in seed.node_types}
    seed_rel_keys = {_norm_key(r.label): r.label for r in seed.relationship_types}

    def describe(info):
        desc = info['descriptions'][0] if info['descriptions'] else ''
        example = info['examples'][0] if info['examples'] else ''
        support = f'discovered in {len(info["doc_keys"])} narratives'
        example_part = f'; e.g. "{example}"' if example else ''
        return f'{desc} ({support}{example_part})'.strip()

    node_types = list(seed.node_types)
    label_by_key = dict(seed_node_keys)
    for key in sorted(agg['node']):
        info = agg['node'][key]
        if key in seed_node_keys or len(info['doc_keys']) < min_support:
            continue
        label = node_label_from_key(key)
        label_by_key[key] = label
        node_types.append(NodeType(
            label=label, description=describe(info), provenance='narrative',
        ))

    relationship_types = list(seed.relationship_types)
    rel_label_by_key = dict(seed_rel_keys)
    patterns = list(seed.patterns)
    for key in sorted(agg['relationship']):
        info = agg['relationship'][key]
        if len(info['doc_keys']) < min_support:
            continue
        if key in seed_rel_keys:
            label = seed_rel_keys[key]
        else:
            label = rel_label_from_key(key)
            rel_label_by_key[key] = label
            relationship_types.append(RelationshipType(
                label=label, description=describe(info), provenance='narrative',
            ))
        for (src_key, dst_key), _count in sorted(info['endpoints'].items()):
            src = label_by_key.get(src_key)
            dst = label_by_key.get(dst_key)
            if src and dst and (src, label, dst) not in patterns:
                patterns.append((src, label, dst))

    # Construct (not model_copy) so the pattern validator re-runs on the
    # merged result.
    return OntologySchema(
        version=version,
        description='Draft schema: deterministic column seed + LLM '
                    'narrative discovery. Human-edit, add competency '
                    'questions, save as schema/v001.yaml, commit.',
        node_types=node_types,
        relationship_types=relationship_types,
        patterns=patterns,
        competency_questions=list(seed.competency_questions),
    )


def write_merge_groups(proposal, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8', newline='\n') as f:
        for group in (proposal.groups if proposal else []):
            f.write(json.dumps(group.model_dump(mode='json')) + '\n')
    return path


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
class DiscoveryState(TypedDict, total=False):
    docs: list                       # sampled corpus Docs
    per_doc: list                    # [(doc_key, NarrativeConcepts|None)]
    aggregated: dict
    proposal: Optional[ConsolidationProposal]
    draft_path: str
    merge_groups_path: str


def build_graph(llm, seed, draft_path=DEFAULT_DRAFT_PATH,
                merge_groups_path=DEFAULT_MERGE_GROUPS_PATH,
                min_support=DEFAULT_MIN_SUPPORT, version='v001-draft'):
    from langgraph.graph import END, START, StateGraph

    seed_labels = [n.label for n in seed.node_types]

    def discover_node(state):
        per_doc = []
        for doc in state['docs']:
            concepts = llm.call(discovery_prompt(doc.text, seed_labels),
                                NarrativeConcepts)
            per_doc.append((doc.doc_key, concepts))
        return {'per_doc': per_doc}

    def aggregate_node(state):
        return {'aggregated': aggregate_concepts(state['per_doc'])}

    def consolidate_node(state):
        summary = candidate_summary(state['aggregated'])
        proposal = None
        if summary:
            proposal = llm.call(consolidation_prompt(summary),
                                ConsolidationProposal)
        return {'proposal': proposal}

    def write_draft_node(state):
        if llm.dry_run:
            return {}
        merged = apply_merge_groups(state['aggregated'], state['proposal'])
        draft = build_draft_schema(seed, merged, version=version,
                                   min_support=min_support)
        dump_schema(draft, draft_path,
                    header='# Generated by ontology/discover.py - edit this '
                           'draft, add competency questions,\n# then save as '
                           'ontology/schema/v001.yaml and commit.')
        write_merge_groups(state['proposal'], merge_groups_path)
        return {'draft_path': str(draft_path),
                'merge_groups_path': str(merge_groups_path)}

    builder = StateGraph(DiscoveryState)
    builder.add_node('discover', discover_node)
    builder.add_node('aggregate', aggregate_node)
    builder.add_node('consolidate', consolidate_node)
    builder.add_node('write_draft', write_draft_node)
    builder.add_edge(START, 'discover')
    builder.add_edge('discover', 'aggregate')
    builder.add_edge('aggregate', 'consolidate')
    builder.add_edge('consolidate', 'write_draft')
    builder.add_edge('write_draft', END)
    return builder.compile()


def run_discovery(docs, llm=None, seed=None, **graph_kwargs):
    llm = llm or CachedLLM()
    seed = seed or build_seed_schema()
    graph = build_graph(llm, seed, **graph_kwargs)
    return graph.invoke({'docs': docs})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--sample', type=int, default=DEFAULT_SAMPLE_SIZE,
                   help=f'Narratives to sample (default {DEFAULT_SAMPLE_SIZE}).')
    p.add_argument('--seed', type=int, default=0, help='Sampling seed.')
    p.add_argument('--min-support', type=int, default=DEFAULT_MIN_SUPPORT,
                   help='Min narratives mentioning a type to keep it.')
    p.add_argument('--limit', type=int, default=None,
                   help='Load only the first N corpus docs (smoke run).')
    p.add_argument('--dry-run', action='store_true',
                   help='Count cache misses without calling the API.')
    args = p.parse_args(argv)

    from corpus import load_corpus
    corpus = load_corpus(limit=args.limit)
    docs = sample_narratives(corpus.docs, n=args.sample, seed=args.seed)
    llm = CachedLLM(dry_run=args.dry_run)
    print(f'discovery over {len(docs)} sampled narratives '
          f'({len(corpus.docs)} corpus docs)')
    state = run_discovery(docs, llm=llm, min_support=args.min_support)
    print(f'stats: {llm.stats}')
    if args.dry_run:
        print(f'--dry-run: {llm.stats["dry_run_misses"]} calls would be paid. '
              'Exit 0.')
        return 0
    print(f'draft:        {state.get("draft_path")}')
    print(f'merge groups: {state.get("merge_groups_path")}')
    print('next: human-edit the draft, add competency questions, save as '
          'ontology/schema/v001.yaml; correct merge groups into '
          'ontology/golden/consolidation.jsonl.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
