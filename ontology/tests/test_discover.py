'''Tests for discover.py — stubbed discovery/consolidation, draft assembly.'''
import json

from corpus import Doc
from discover import (
    CandidateNodeType,
    CandidateRelationshipType,
    ConsolidationProposal,
    MergeGroup,
    NarrativeConcepts,
    aggregate_concepts,
    run_discovery,
    sample_narratives,
)
from llm import CachedLLM
from schema_model import load_schema
from seed_schema import build_seed_schema


def make_doc(key, text, entity='waymo'):
    import hashlib
    return Doc(doc_key=key, report_id=key, same_incident_id=None, text=text,
               text_sha256=hashlib.sha256(text.encode()).hexdigest(),
               row={'master_entity': entity})


THREE_DOCS = [
    make_doc('D1', 'A pedestrian crossed against the light.'),
    make_doc('D2', 'A person on foot entered the roadway.'),
    make_doc('D3', 'The vehicle stopped at a red light.'),
]

STRUCK = CandidateRelationshipType(
    name='STRUCK', source='Vehicle', target='Pedestrian',
    example_mention='struck the pedestrian')


def concept_factory(prompt, schema):
    if schema is NarrativeConcepts:
        if 'pedestrian crossed' in prompt:
            return NarrativeConcepts(
                node_types=[CandidateNodeType(name='Pedestrian',
                                              example_mention='a pedestrian')],
                relationship_types=[STRUCK])
        if 'person on foot' in prompt:
            return NarrativeConcepts(
                node_types=[CandidateNodeType(name='Person On Foot',
                                              example_mention='a person on foot')],
                relationship_types=[STRUCK])
        return NarrativeConcepts()
    if schema is ConsolidationProposal:
        return ConsolidationProposal(groups=[MergeGroup(
            kind='node', canonical_name='Pedestrian',
            members=['Pedestrian', 'Person On Foot'])])
    raise AssertionError(f'unexpected schema {schema}')


def run(tmp_path, client, **kwargs):
    llm = CachedLLM(model_id='test-model', cache_dir=tmp_path / 'cache',
                    _client=client, _sleep=lambda s: None,
                    dry_run=kwargs.pop('dry_run', False))
    state = run_discovery(
        THREE_DOCS, llm=llm, seed=build_seed_schema(),
        draft_path=tmp_path / 'drafts' / 'v001-draft.yaml',
        merge_groups_path=tmp_path / 'drafts' / 'v001-draft-merge-groups.jsonl',
        **kwargs)
    return llm, state


def test_discovery_aggregates_candidates_across_narratives(
        tmp_path, stub_llm_factory):
    client = stub_llm_factory(response_factory=concept_factory)
    _, state = run(tmp_path, client)
    agg = state['aggregated']
    assert set(agg['node']) == {'pedestrian', 'person on foot'}
    assert agg['relationship']['struck']['doc_keys'] == {'D1', 'D2'}


def test_consolidation_merges_synonyms_into_one_type(
        tmp_path, stub_llm_factory):
    client = stub_llm_factory(response_factory=concept_factory)
    _, state = run(tmp_path, client)
    draft = load_schema(state['draft_path'])
    labels = [n.label for n in draft.node_types]
    assert 'Pedestrian' in labels
    assert 'PersonOnFoot' not in labels
    # merged support: 2 docs, so it survives min_support=2
    ped = draft.node_type('Pedestrian')
    assert 'discovered in 2 narratives' in ped.description


def test_draft_provenance_tags(tmp_path, stub_llm_factory):
    client = stub_llm_factory(response_factory=concept_factory)
    _, state = run(tmp_path, client)
    draft = load_schema(state['draft_path'])
    assert draft.node_type('Pedestrian').provenance == 'narrative'
    assert draft.node_type('Incident').provenance == 'column'
    assert ('Vehicle', 'STRUCK', 'Pedestrian') in draft.patterns


def test_merge_groups_emitted_in_scoreable_shape(tmp_path, stub_llm_factory):
    client = stub_llm_factory(response_factory=concept_factory)
    _, state = run(tmp_path, client)
    with open(state['merge_groups_path'], encoding='utf-8') as f:
        lines = [json.loads(line) for line in f]
    assert lines  # one MergeGroup per line, the shape the consolidation eval scores
    group = MergeGroup.model_validate(lines[0])
    assert group.kind == 'node'
    assert set(group.members) == {'Pedestrian', 'Person On Foot'}


def test_second_run_is_all_cache_hits(tmp_path, stub_llm_factory):
    run(tmp_path, stub_llm_factory(response_factory=concept_factory))
    second_client = stub_llm_factory()  # any call would raise
    llm, _ = run(tmp_path, second_client)
    assert second_client.calls == []
    assert llm.stats['llm_calls'] == 0
    assert llm.stats['cache_hits'] == 4  # 3 discovery + 1 consolidation


def test_prompt_change_invalidates_cache(tmp_path, stub_llm_factory):
    run(tmp_path, stub_llm_factory(response_factory=concept_factory))
    changed = [make_doc('D1', 'A pedestrian crossed against the light. Updated.'),
               THREE_DOCS[1], THREE_DOCS[2]]
    client = stub_llm_factory(response_factory=concept_factory)
    llm = CachedLLM(model_id='test-model', cache_dir=tmp_path / 'cache',
                    _client=client, _sleep=lambda s: None)
    run_discovery(changed, llm=llm, seed=build_seed_schema(),
                  draft_path=tmp_path / 'drafts' / 'v001-draft.yaml',
                  merge_groups_path=tmp_path / 'drafts' / 'mg.jsonl')
    # D1's prompt changed -> one paid call; D2/D3 still hit; consolidation
    # input is unchanged (same aggregate) -> hit.
    assert llm.stats['llm_calls'] == 1
    assert llm.stats['cache_hits'] == 3


def test_dry_run_writes_nothing_and_counts_misses(tmp_path, stub_llm_factory):
    client = stub_llm_factory()
    llm, state = run(tmp_path, client, dry_run=True)
    assert client.calls == []
    assert llm.stats['dry_run_misses'] == 3  # consolidation skipped: no aggregate
    assert 'draft_path' not in state
    assert not (tmp_path / 'drafts').exists()


def test_sample_narratives_stratified_and_deterministic():
    docs = ([make_doc(f'W{i}', f'waymo doc {i}', 'waymo') for i in range(30)]
            + [make_doc(f'C{i}', f'cruise doc {i}', 'cruise') for i in range(10)]
            + [make_doc('SKIP', '', 'waymo')])
    docs[-1].skip_reason = 'skipped_redacted'
    a = sample_narratives(docs, n=8, seed=42)
    b = sample_narratives(docs, n=8, seed=42)
    assert [d.doc_key for d in a] == [d.doc_key for d in b]
    assert len(a) == 8
    entities = {d.row['master_entity'] for d in a}
    assert entities == {'waymo', 'cruise'}     # both strata represented
    assert all(d.doc_key != 'SKIP' for d in a)  # skipped docs excluded


def test_aggregate_skips_none_results():
    agg = aggregate_concepts([('D1', None), ('D2', NarrativeConcepts(
        node_types=[CandidateNodeType(name='Animal')]))])
    assert set(agg['node']) == {'animal'}
