'''Tests for golden.py — sampling, splits, record validation, staleness.'''
import pytest

from golden import (
    annotation_counts,
    check_staleness,
    prelabel_doc,
    split_dev_heldout,
    stratified_sample,
    validate_golden_record,
)
from llm import CachedLLM
from test_extract import extraction_factory, make_doc
from test_prune import narrative_schema


def corpus_docs():
    docs = []
    for i in range(30):
        entity = 'waymo' if i % 3 else 'cruise'
        text = ('short doc. ' if i % 2 else 'a much longer narrative text '
                'with many more words in it to land in another bucket. ') * (i % 5 + 1)
        d = make_doc(f'INC-{i:02d}', text)
        d.row['master_entity'] = entity
        d.row['automation_system_type'] = 'ADS' if i % 4 else 'ADAS'
        docs.append(d)
    for i in range(4):
        d = make_doc(f'RED-{i}', '', skip_reason='skipped_redacted')
        docs.append(d)
    return docs


def test_sampler_excludes_redacted_except_deliberate_keeps():
    sampled, report = stratified_sample(corpus_docs(), n=12, seed=1,
                                        include_redacted=2)
    redacted = [d for d in sampled if d.skip_reason]
    assert len(redacted) == 2
    assert report['n_redacted_kept'] == 2
    assert len(sampled) <= 12

    none_kept, _ = stratified_sample(corpus_docs(), n=12, seed=1,
                                     include_redacted=0)
    assert all(not d.skip_reason for d in none_kept)


def test_sampler_covers_strata():
    sampled, _ = stratified_sample(corpus_docs(), n=14, seed=1)
    entities = {d.row['master_entity'] for d in sampled if not d.skip_reason}
    assert entities == {'waymo', 'cruise'}


def test_sampler_returns_exactly_n_despite_rounding():
    # Three equal strata with target 10: per-stratum round() quotas sum to
    # 9; the redistribution pass must top the sample back up to 10.
    docs = []
    for entity in ('waymo', 'cruise', 'zoox'):
        for i in range(20):
            d = make_doc(f'{entity}-{i:02d}', f'{entity} narrative {i}. ' * 3)
            d.row['master_entity'] = entity
            d.row['automation_system_type'] = 'ADS'
            docs.append(d)
    sampled, _ = stratified_sample(docs, n=10, seed=5, include_redacted=0)
    assert len(sampled) == 10


def test_sampler_is_deterministic():
    a, _ = stratified_sample(corpus_docs(), n=12, seed=7)
    b, _ = stratified_sample(corpus_docs(), n=12, seed=7)
    assert [d.doc_key for d in a] == [d.doc_key for d in b]


def test_split_disjoint_and_stable():
    sampled, _ = stratified_sample(corpus_docs(), n=15, seed=3)
    dev_a, held_a = split_dev_heldout(sampled, dev_size=5, seed=3)
    dev_b, held_b = split_dev_heldout(sampled, dev_size=5, seed=3)
    assert [d.doc_key for d in dev_a] == [d.doc_key for d in dev_b]
    assert [d.doc_key for d in held_a] == [d.doc_key for d in held_b]
    assert not ({d.doc_key for d in dev_a} & {d.doc_key for d in held_a})
    assert len(dev_a) == 5


def test_prelabel_output_conforms_to_extraction_shape(
        tmp_path, stub_llm_factory):
    doc = make_doc('INC-1', 'A pedestrian entered the roadway. The AV braked.')
    llm = CachedLLM(model_id='sonnet-test', cache_dir=tmp_path,
                    _client=stub_llm_factory(response_factory=extraction_factory),
                    _sleep=lambda s: None)
    record = prelabel_doc(doc, narrative_schema(), llm, 'dev')

    validate_golden_record(record, narrative_schema())
    assert record['split'] == 'dev'
    assert record['guidelines_version'] == 'v0.1'
    assert record['text_sha256'] == doc.text_sha256
    # same per-entity shape extraction emits
    sample_entity = record['entities'][0]
    assert {'key', 'type', 'name', 'provenance', 'quote',
            'properties'} <= set(sample_entity)
    provs = {e['provenance'] for e in record['entities']}
    assert provs == {'column', 'narrative'}


def test_golden_record_fixture_validates():
    record = {
        'doc_key': 'INC-1', 'split': 'dev', 'guidelines_version': 'v0.1',
        'text_sha256': 'abc', 'status': 'ok',
        'entities': [
            {'key': 'INC-1:Pedestrian:1', 'type': 'Pedestrian',
             'name': 'pedestrian', 'provenance': 'narrative', 'quote': 'q',
             'properties': {}},
            {'key': 'INC-1:UNMAPPED:1', 'type': 'UNMAPPED',
             'name': 'fire truck crew', 'provenance': 'narrative',
             'quote': 'q', 'properties': {},
             'candidate_type': 'EmergencyResponder'},
        ],
        'relationships': [],
    }
    assert validate_golden_record(record, narrative_schema())


def test_unmapped_without_candidate_type_rejected():
    record = {
        'doc_key': 'INC-1', 'split': 'dev', 'guidelines_version': 'v0.1',
        'text_sha256': 'abc',
        'entities': [{'key': 'k1', 'type': 'UNMAPPED', 'name': 'x',
                      'provenance': 'narrative', 'quote': 'q',
                      'properties': {}}],
        'relationships': [],
    }
    with pytest.raises(ValueError, match='candidate_type'):
        validate_golden_record(record, narrative_schema())


def test_relationship_referencing_unknown_key_rejected():
    record = {
        'doc_key': 'INC-1', 'split': 'dev', 'guidelines_version': 'v0.1',
        'text_sha256': 'abc',
        'entities': [{'key': 'k1', 'type': 'Pedestrian', 'name': 'p',
                      'provenance': 'narrative', 'quote': 'q',
                      'properties': {}}],
        'relationships': [{'type': 'STRUCK', 'source_key': 'GHOST',
                           'target_key': 'k1', 'provenance': 'narrative'}],
    }
    with pytest.raises(ValueError, match='GHOST'):
        validate_golden_record(record, narrative_schema())


def test_staleness_detects_text_hash_mismatch():
    doc = make_doc('INC-1', 'current text')
    records = [
        {'doc_key': 'INC-1', 'text_sha256': 'stale-hash'},
        {'doc_key': 'GONE', 'text_sha256': 'x'},
    ]
    stale = check_staleness(records, {'INC-1': doc})
    assert ('INC-1', 'text hash mismatch') in stale
    assert ('GONE', 'missing from corpus') in stale

    fresh = [{'doc_key': 'INC-1', 'text_sha256': doc.text_sha256}]
    assert check_staleness(fresh, {'INC-1': doc}) == []


def test_annotation_counts_report_annotation_level():
    records = [
        {'entities': [1, 2, 3], 'relationships': [1]},
        {'entities': [1], 'relationships': []},
    ]
    assert annotation_counts(records) == {'docs': 2, 'entities': 4,
                                          'relationships': 1}
