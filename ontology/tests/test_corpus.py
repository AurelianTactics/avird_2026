'''Hermetic tests for corpus.py — DataFrame fixtures, no DB, no network.'''
import pandas as pd
import pytest

import corpus
from corpus import (
    SKIP_EMPTY,
    SKIP_REDACTED,
    Corpus,
    corpus_from_frame,
    preprocess_narrative,
)

REDACTED_CELL = '[REDACTED, MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION]'


def make_frame(rows):
    '''Frame builder with the columns corpus.py reads, NaN-filled by default.'''
    base = {
        'Report ID': None,
        'Same Incident ID': None,
        'Narrative - Same Incident ID': None,
        'Narrative': None,
        'master_entity': 'waymo',
        'built_at': '2026-03-16T00:00:00+00:00',
        'source_batch_ids': 'batch-a,batch-b',
    }
    return pd.DataFrame([{**base, **r} for r in rows])


# ---------------------------------------------------------------------------
# preprocess_narrative
# ---------------------------------------------------------------------------
def test_separator_removed_from_merged_narrative():
    raw = 'Latest report text.\n\n--- next report ---\n\nEarlier report text.'
    text, skip = preprocess_narrative(raw)
    assert skip is None
    assert 'next report' not in text
    assert 'Latest report text.' in text
    assert 'Earlier report text.' in text


def test_whole_cell_redacted_is_skipped_not_emptied():
    text, skip = preprocess_narrative(REDACTED_CELL)
    assert skip == SKIP_REDACTED
    assert text == ''


def test_redacted_segment_dropped_but_readable_segment_kept():
    raw = f'Readable narrative.\n\n--- next report ---\n\n{REDACTED_CELL}'
    text, skip = preprocess_narrative(raw)
    assert skip is None
    assert text == 'Readable narrative.'


def test_inline_redaction_spans_stripped():
    raw = 'The vehicle struck [XXX] near XXXX street.'
    text, skip = preprocess_narrative(raw)
    assert skip is None
    assert 'XXX' not in text
    assert '  ' not in text  # span removal must not leave double spaces


def test_whitespace_normalized_deterministically():
    raw = '  Leading and   internal\truns.\nNext line.  '
    text, _ = preprocess_narrative(raw)
    assert text == 'Leading and internal runs.\nNext line.'


def test_empty_after_cleaning_is_skipped():
    for raw in (None, '', '   ', '[XXX] XXXX'):
        text, skip = preprocess_narrative(raw)
        assert skip == SKIP_EMPTY, raw
        assert text == ''


def test_preprocessing_is_byte_stable():
    raw = 'Some [XXX] narrative.\n\n--- next report ---\n\nOlder  text.'
    a, _ = preprocess_narrative(raw)
    b, _ = preprocess_narrative(raw)
    assert a.encode('utf-8') == b.encode('utf-8')


# ---------------------------------------------------------------------------
# corpus_from_frame
# ---------------------------------------------------------------------------
def test_merged_column_missing_falls_back_to_narrative():
    df = make_frame([{'Report ID': 'R1', 'Narrative': 'Plain narrative.'}])
    df = df.drop(columns=['Narrative - Same Incident ID'])
    out = corpus_from_frame(df)
    assert out.docs[0].text == 'Plain narrative.'


def test_merged_cell_empty_falls_back_to_narrative():
    df = make_frame([{
        'Report ID': 'R1',
        'Narrative - Same Incident ID': None,
        'Narrative': 'Fallback narrative.',
    }])
    out = corpus_from_frame(df)
    assert out.docs[0].text == 'Fallback narrative.'


def test_doc_key_prefers_same_incident_id_then_report_id():
    df = make_frame([
        {'Same Incident ID': 'INC-1', 'Report ID': 'R1', 'Narrative': 'a'},
        {'Report ID': 'R2', 'Narrative': 'b'},
    ])
    keys = [d.doc_key for d in corpus_from_frame(df).docs]
    assert keys == sorted(['INC-1', 'R2'])
    by_key = {d.doc_key: d for d in corpus_from_frame(df).docs}
    assert by_key['INC-1'].same_incident_id == 'INC-1'
    assert by_key['R2'].same_incident_id is None


def test_limit_returns_exactly_n_with_stable_ordering():
    rows = [{'Report ID': f'R{i:02d}', 'Narrative': f'doc {i}'} for i in range(10)]
    df = make_frame(rows)
    shuffled = df.sample(frac=1, random_state=7).reset_index(drop=True)
    first = corpus_from_frame(df, limit=5)
    second = corpus_from_frame(shuffled, limit=5)
    assert len(first.docs) == 5
    assert [d.doc_key for d in first.docs] == [d.doc_key for d in second.docs]


def test_explicit_doc_key_list_returns_exactly_those():
    rows = [{'Report ID': f'R{i}', 'Narrative': f'doc {i}'} for i in range(5)]
    out = corpus_from_frame(make_frame(rows), doc_keys=['R3', 'R1'])
    assert [d.doc_key for d in out.docs] == ['R3', 'R1']


def test_missing_doc_key_raises():
    df = make_frame([{'Report ID': 'R1', 'Narrative': 'a'}])
    with pytest.raises(ValueError, match='NOPE'):
        corpus_from_frame(df, doc_keys=['NOPE'])


def test_skipped_doc_still_carries_structured_row():
    df = make_frame([{
        'Report ID': 'R1',
        'Narrative': REDACTED_CELL,
        'master_entity': 'cruise',
    }])
    out = corpus_from_frame(df)
    doc = out.docs[0]
    assert doc.skip_reason == SKIP_REDACTED
    assert doc.row['master_entity'] == 'cruise'
    assert out.skip_counts == {SKIP_REDACTED: 1}


def test_snapshot_carries_built_at_and_batches():
    df = make_frame([{'Report ID': 'R1', 'Narrative': 'a'}])
    snap = corpus_from_frame(df).snapshot
    assert snap['built_at'] == '2026-03-16T00:00:00+00:00'
    assert snap['source_batch_ids'] == 'batch-a,batch-b'
    assert snap['n_canonical_rows'] == 1


def test_long_text_flagged_not_chunked():
    df = make_frame([{'Report ID': 'R1', 'Narrative': 'x' * 9000}])
    doc = corpus_from_frame(df).docs[0]
    assert 'long_text' in doc.flags
    assert len(doc.text) == 9000


def test_text_sha256_matches_text():
    import hashlib
    df = make_frame([{'Report ID': 'R1', 'Narrative': 'Some text.'}])
    doc = corpus_from_frame(df).docs[0]
    assert doc.text_sha256 == hashlib.sha256(doc.text.encode('utf-8')).hexdigest()
