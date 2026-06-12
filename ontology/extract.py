'''LangGraph graph 2: schema-constrained instance extraction over N documents.

Per document (``Send`` fan-out, concurrency capped for the tier-1 rate
limit): structured-output extraction against flat Pydantic models derived
from the frozen schema → prune.py validation (quote check, label/pattern
check with direction correction, dangling-relationship drops) → stable entity
keys → one JSONL line appended incrementally to
``ontology/artifacts/extractions/<run_id>.jsonl``.

Structured-column facts (incident, subject vehicle, company, location,
conditions) are instantiated deterministically — no LLM — and tagged
``provenance: column``; the LLM extracts only what narratives add, tagged
``provenance: narrative``. When a narrative mention resolves to the same key
as a column entity, *both* instance records are kept in the artifact (the
graph MERGE collapses them on load; extraction eval scores narrative
instances only).

Skip-redacted docs bypass the LLM but still emit their column entities. The
artifact is the source of truth; Neo4j is a rebuildable projection.

Run from the repo root (needs ``DATABASE_URL`` + ``ANTHROPIC_API_KEY``)::

    python ontology/extract.py --limit 5 --dry-run
    python ontology/extract.py --limit 100 --include-golden
'''
import argparse
import json
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from pydantic import ConfigDict, Field, create_model

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import operator  # noqa: E402

from llm import CachedLLM  # noqa: E402
from prune import (  # noqa: E402
    EntityKeyer,
    PrunedEntity,
    PrunedRelationship,
    prune_extraction,
)
from run_records import RunRecorder, new_run_id  # noqa: E402
from schema_model import load_frozen_schema  # noqa: E402

PROMPT_VERSION = 'p001'
DEFAULT_SCHEMA_PATH = _HERE / 'schema' / 'v001.yaml'
EXTRACTIONS_DIR = _HERE / 'artifacts' / 'extractions'
GOLDEN_DIR = _HERE / 'golden'
DEFAULT_MAX_CONCURRENCY = 4

_TRUTHY = {'1', 'true', 'yes', 'y', 't'}


# ---------------------------------------------------------------------------
# Structured-output models derived from the frozen schema
# ---------------------------------------------------------------------------
def build_extraction_model(schema):
    '''Flat Pydantic models with Literal-constrained type fields.'''
    node_lit = Literal[tuple(n.label for n in schema.node_types)]
    rel_lit = Literal[tuple(r.label for r in schema.relationship_types)]
    entity_model = create_model(
        'ExtractedEntity',
        __config__=ConfigDict(extra='forbid'),
        type=(node_lit, ...),
        name=(str, ...),
        supporting_quote=(str, ...),
        properties=(dict[str, str], Field(default_factory=dict)),
    )
    relationship_model = create_model(
        'ExtractedRelationship',
        __config__=ConfigDict(extra='forbid'),
        type=(rel_lit, ...),
        source_type=(node_lit, ...),
        source_name=(str, ...),
        target_type=(node_lit, ...),
        target_name=(str, ...),
        supporting_quote=(str, ...),
    )
    return create_model(
        'DocExtraction',
        __config__=ConfigDict(extra='forbid'),
        entities=(list[entity_model], Field(default_factory=list)),
        relationships=(list[relationship_model], Field(default_factory=list)),
    )


def extraction_prompt(schema, text):
    node_lines = '\n'.join(f'- {n.label}: {n.description}'
                           for n in schema.node_types)
    pattern_lines = '\n'.join(f'- ({s})-[:{r}]->({t})'
                              for s, r, t in schema.patterns)
    return (
        'Extract entity and relationship instances from this autonomous-'
        'vehicle crash narrative, conforming to the schema below.\n\n'
        f'Entity types:\n{node_lines}\n\n'
        f'Allowed relationship patterns:\n{pattern_lines}\n\n'
        'Rules:\n'
        '- Extract only what the narrative itself states. Structured facts '
        '(subject-vehicle make/model, company, date) are already captured '
        'elsewhere; extract them only when the narrative adds information.\n'
        '- Every entity and relationship carries a short supporting_quote '
        'copied verbatim from the narrative.\n'
        '- Relationship source/target name+type must match an entity you '
        'extracted.\n'
        '- Use only the listed types and patterns.\n\n'
        f'Narrative:\n{text}'
    )


# ---------------------------------------------------------------------------
# Deterministic column-provenance instances (no LLM)
# ---------------------------------------------------------------------------
WEATHER_FLAGS = {
    'weather_clear_clean': 'Clear',
    'weather_snow_clean': 'Snow',
    'weather_cloudy_clean': 'Cloudy',
    'weather_fog_smoke_clean': 'Fog/Smoke',
    'weather_rain_clean': 'Rain',
    'weather_severe_wind_clean': 'Severe Wind',
}
ROADWAY_FLAGS = {
    'roadway_wet_surface_clean': 'Wet Surface',
    'roadway_work_zone_clean': 'Work Zone',
    'roadway_degraded_marking_clean': 'Degraded Marking',
    'roadway_traffic_incident_clean': 'Traffic Incident',
}
LOCATION_COLUMNS = {
    'city': 'City', 'state': 'State', 'zip_code': 'Zip Code',
    'roadway_type': 'Roadway Type', 'roadway_surface': 'Roadway Surface',
    'roadway_description': 'Roadway Description',
    'posted_speed_limit_mph': 'Posted Speed Limit (MPH)',
}
VEHICLE_COLUMNS = {
    'vin': 'VIN', 'make': 'Make Clean', 'model': 'Model Clean',
    'model_year': 'Model Year', 'mileage': 'Mileage',
    'automation_system_type': 'automation_system_type',
    'automation_engaged': 'automation_engaged_clean',
    'precrash_speed_mph': 'sv_precrash_speed_mph',
    'precrash_movement': 'SV Pre-Crash Movement',
}
# 'Crash With' values that imply a partner *vehicle* (vs pedestrian/cyclist/
# fixed object, which only the narrative can characterize).
_PARTNER_VEHICLE_KEYWORDS = (
    'vehicle', 'car', 'truck', 'van', 'bus', 'motorcycle', 'suv', 'pickup',
)

INCIDENT_COLUMNS = {
    'report_id': 'Report ID', 'incident_date': 'incident_date',
    'incident_time': 'Incident Time (24:00)',
    'highest_injury_severity': 'Highest Injury Severity Alleged',
    'crash_with': 'Crash With',
}


def _flag_on(value):
    return str(value).strip().lower() in _TRUTHY


def column_instances(doc):
    '''Deterministic entities/relationships from structured columns.'''
    row = doc.row
    ik = doc.doc_key
    keyer = EntityKeyer(ik)
    entities, relationships = [], []

    def props_from(mapping):
        return {prop: str(row[col]) for prop, col in mapping.items()
                if row.get(col) not in (None, '')}

    def add_rel(rel_type, source_key, target_key):
        relationships.append(PrunedRelationship(
            type=rel_type, source_key=source_key, target_key=target_key,
            provenance='column'))

    incident = PrunedEntity(
        key=ik, type='Incident', name=ik, provenance='column',
        properties={'incident_key': ik, **props_from(INCIDENT_COLUMNS)})
    entities.append(incident)

    sv_key = keyer.key_for('Vehicle', 'subject vehicle', is_subject=True,
                           vin=row.get('VIN'))
    sv_props = props_from(VEHICLE_COLUMNS)
    sv_props.update({'vehicle_key': sv_key, 'is_subject_vehicle': 'true'})
    entities.append(PrunedEntity(
        key=sv_key, type='Vehicle', name='subject vehicle',
        provenance='column', properties=sv_props))
    add_rel('INVOLVES', ik, sv_key)

    company_name = row.get('master_entity')
    if company_name:
        company_key = keyer.key_for('Company', company_name)
        entities.append(PrunedEntity(
            key=company_key, type='Company', name=str(company_name),
            provenance='column',
            properties={'name': str(company_name),
                        **({'reporting_entity': str(row['Reporting Entity'])}
                           if row.get('Reporting Entity') else {})}))
        add_rel('OPERATED_BY', sv_key, company_key)
        add_rel('REPORTED_BY', ik, company_key)

    loc_props = props_from(LOCATION_COLUMNS)
    if loc_props:
        loc_key = f'{ik}:LOC'
        entities.append(PrunedEntity(
            key=loc_key, type='Location', name=f'location of {ik}',
            provenance='column',
            properties={'location_key': loc_key, **loc_props}))
        add_rel('OCCURRED_AT', ik, loc_key)

    conditions = []
    for col, name in {**WEATHER_FLAGS, **ROADWAY_FLAGS}.items():
        if col in row and _flag_on(row[col]):
            category = 'weather' if col in WEATHER_FLAGS else 'roadway'
            conditions.append((name, category))
    if row.get('Lighting'):
        conditions.append((str(row['Lighting']), 'lighting'))
    for name, category in conditions:
        cond_key = keyer.key_for('EnvironmentalCondition', name)
        entities.append(PrunedEntity(
            key=cond_key, type='EnvironmentalCondition', name=name,
            provenance='column',
            properties={'name': name, 'category': category}))
        add_rel('HAD_CONDITION', ik, cond_key)

    crash_with = str(row.get('Crash With') or '').lower()
    if any(kw in crash_with for kw in _PARTNER_VEHICLE_KEYWORDS):
        partner_key = keyer.key_for('Vehicle', 'crash partner vehicle')
        partner_props = {'vehicle_key': partner_key,
                         'is_subject_vehicle': 'false'}
        if row.get('CP Pre-Crash Movement'):
            partner_props['precrash_movement'] = str(row['CP Pre-Crash Movement'])
        entities.append(PrunedEntity(
            key=partner_key, type='Vehicle', name='crash partner vehicle',
            provenance='column', properties=partner_props))
        add_rel('INVOLVES', ik, partner_key)
        add_rel('COLLIDED_WITH', sv_key, partner_key)

    return entities, relationships, keyer


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------
class ArtifactWriter:
    '''Thread-safe incremental JSONL appender (Send fan-out runs in threads).'''

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, record):
        line = json.dumps(record, default=str)
        with self._lock:
            with self.path.open('a', encoding='utf-8', newline='\n') as f:
                f.write(line + '\n')


def _entity_record(e):
    return asdict(e)


def _relationship_record(r):
    return asdict(r)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
class ExtractState(TypedDict):
    docs: list
    results: Annotated[list, operator.add]


def build_graph(schema, llm, writer, recorder=None):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import Send

    doc_extraction_model = build_extraction_model(schema)

    def fan_out(state):
        return [Send('extract_doc', {'doc': doc}) for doc in state['docs']]

    def extract_doc(state):
        doc = state['doc']
        t0 = time.perf_counter()
        counters = {}
        entities, relationships, keyer = column_instances(doc)
        status = 'ok'

        if doc.skip_reason:
            status = doc.skip_reason
        else:
            raw = llm.call(extraction_prompt(schema, doc.text),
                           doc_extraction_model)
            if raw is None:
                status = 'dry_run_miss'
            else:
                pruned = prune_extraction(schema, raw, doc.text, doc.doc_key,
                                          keyer=keyer)
                counters = pruned.counters
                seen = {(e.key, e.provenance) for e in entities}
                for e in pruned.entities:
                    if (e.key, e.provenance) not in seen:
                        entities.append(e)
                relationships.extend(pruned.relationships)

        latency = round(time.perf_counter() - t0, 3)
        if not llm.dry_run:
            writer.append({
                'doc_key': doc.doc_key,
                'status': status,
                'text_sha256': doc.text_sha256,
                'text': doc.text,
                'flags': doc.flags,
                'entities': [_entity_record(e) for e in entities],
                'relationships': [_relationship_record(r) for r in relationships],
                'counters': counters,
            })
            if recorder is not None:
                recorder.record_doc(
                    doc.doc_key, status=status, counters=counters,
                    n_entities=len(entities),
                    n_relationships=len(relationships),
                    latency_seconds=latency)
        return {'results': [{'doc_key': doc.doc_key, 'status': status,
                             'counters': counters}]}

    builder = StateGraph(ExtractState)
    builder.add_node('extract_doc', extract_doc)
    builder.add_conditional_edges(START, fan_out, ['extract_doc'])
    builder.add_edge('extract_doc', END)
    return builder.compile()


def run_extraction(docs, schema, llm, artifact_path, recorder=None,
                   max_concurrency=DEFAULT_MAX_CONCURRENCY):
    writer = ArtifactWriter(artifact_path)
    graph = build_graph(schema, llm, writer, recorder=recorder)
    state = graph.invoke({'docs': docs, 'results': []},
                         config={'max_concurrency': max_concurrency})
    return state


def aggregate_counters(results):
    totals = {}
    statuses = {}
    for r in results:
        statuses[r['status']] = statuses.get(r['status'], 0) + 1
        for name, count in r['counters'].items():
            totals[name] = totals.get(name, 0) + count
    return totals, statuses


def golden_doc_keys(golden_dir=GOLDEN_DIR):
    keys = []
    for name in ('dev.jsonl', 'heldout.jsonl'):
        path = Path(golden_dir) / name
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    keys.append(json.loads(line)['doc_key'])
    return keys


def select_docs(corpus_docs, limit=None, include_golden=False,
                golden_dir=GOLDEN_DIR):
    '''First-N (stable order) plus, optionally, every golden doc.'''
    selected = list(corpus_docs if limit is None else corpus_docs[:limit])
    if include_golden:
        have = {d.doc_key for d in selected}
        by_key = {d.doc_key: d for d in corpus_docs}
        missing_golden = [k for k in golden_doc_keys(golden_dir)
                          if k not in have]
        absent = [k for k in missing_golden if k not in by_key]
        if absent:
            raise ValueError(f'golden doc keys not in corpus: {absent[:5]}')
        selected.extend(by_key[k] for k in missing_golden)
    return selected


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument('--schema', default=str(DEFAULT_SCHEMA_PATH),
                   help='Frozen schema path (drafts/ are refused).')
    p.add_argument('--limit', type=int, default=100,
                   help='Extract the first N docs (default 100; 0 = full corpus).')
    p.add_argument('--include-golden', action='store_true',
                   help='Always include golden dev/held-out docs in the run.')
    p.add_argument('--max-concurrency', type=int,
                   default=DEFAULT_MAX_CONCURRENCY,
                   help='Parallel doc extractions (tier-1 rate limit: keep ~4-5).')
    p.add_argument('--dry-run', action='store_true',
                   help='Count docs and cache misses; zero LLM calls, no writes.')
    args = p.parse_args(argv)

    schema = load_frozen_schema(args.schema)
    from corpus import load_corpus
    corpus = load_corpus()
    docs = select_docs(corpus.docs, limit=args.limit or None,
                       include_golden=args.include_golden)

    llm = CachedLLM(dry_run=args.dry_run)
    run_id = new_run_id('extract')
    artifact_path = EXTRACTIONS_DIR / f'{run_id}.jsonl'
    recorder = None if args.dry_run else RunRecorder(
        'extract', run_id=run_id, schema_path=args.schema,
        schema_version=schema.version, prompt_version=PROMPT_VERSION,
        model_id=llm.model_id, data_snapshot=corpus.snapshot)

    print(f'extraction over {len(docs)} docs '
          f'(schema {schema.version}, run {run_id})')
    state = run_extraction(docs, schema, llm, artifact_path,
                           recorder=recorder,
                           max_concurrency=args.max_concurrency)
    totals, statuses = aggregate_counters(state['results'])
    print(f'statuses: {statuses}')
    print(f'drop/correction counters: {totals}')
    print(f'llm stats: {llm.stats}')
    if args.dry_run:
        print(f'--dry-run: {llm.stats["dry_run_misses"]} calls would be paid. '
              'Exit 0.')
        return 0
    recorder.write_summary(llm_stats=llm.stats, counters=totals,
                           statuses=statuses, artifact=str(artifact_path),
                           n_docs=len(docs))
    print(f'artifact: {artifact_path}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
