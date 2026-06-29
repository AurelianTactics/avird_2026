'''judge_batch: stubbed LLM, sqlite — verdicts, sentinels, upsert, cache.'''
import judge_batch
from graph import FaultVerdict
from llm import CachedLLM
from sqlalchemy import text

from conftest import StubClient

ROW = {
    'Report ID': 'RPT-1',
    'Narrative': 'The AV ran a red light and struck a stopped car.',
    'Operating Entity': 'Waymo LLC',
}


def _rows(conn):
    return list(conn.execute(text(
        'SELECT report_id, fault_version, is_av_at_fault, av_fault_percentage, '
        'short_explanation_of_decision, model FROM fault_analysis'
    )).mappings())


def test_valid_verdict_is_written_with_parsed_values(engine, tmp_path):
    stub = StubClient(response=FaultVerdict(
        is_av_at_fault=True,
        av_fault_percentage=0.9,
        short_explanation_of_decision='AV ran a red light.',
    ))
    llm = CachedLLM(cache_dir=tmp_path / 'cache', _client=stub)
    stats = judge_batch.run_batch([ROW], llm, engine, 'v1')

    assert stats['written'] == 1
    assert stats['errors'] == 0
    with engine.connect() as conn:
        rows = _rows(conn)
    assert len(rows) == 1
    assert rows[0]['report_id'] == 'RPT-1'
    assert bool(rows[0]['is_av_at_fault']) is True
    assert float(rows[0]['av_fault_percentage']) == 0.9
    assert rows[0]['short_explanation_of_decision'] == 'AV ran a red light.'
    assert rows[0]['model'] == llm.model_id


def test_out_of_range_percentage_stores_error_sentinel(engine, tmp_path):
    # A structurally valid but out-of-range verdict must collapse to the
    # sentinel — never a guessed/clamped value.
    stub = StubClient(response=FaultVerdict(
        is_av_at_fault=True,
        av_fault_percentage=2.0,
        short_explanation_of_decision='nonsense',
    ))
    llm = CachedLLM(cache_dir=tmp_path / 'cache', _client=stub)
    stats = judge_batch.run_batch([ROW], llm, engine, 'v1')

    assert stats['errors'] == 1
    with engine.connect() as conn:
        rows = _rows(conn)
    assert rows[0]['is_av_at_fault'] is None
    assert rows[0]['av_fault_percentage'] is None
    assert rows[0]['short_explanation_of_decision'] == judge_batch.ERROR_SENTINEL_TEXT


def test_malformed_output_stores_error_sentinel(engine, tmp_path):
    # The client returns a dict missing required keys -> CachedLLM validation
    # raises LLMCallError -> graph reports an error -> batch writes the sentinel.
    stub = StubClient(response={'is_av_at_fault': True})  # missing fields
    llm = CachedLLM(cache_dir=tmp_path / 'cache', _client=stub)
    stats = judge_batch.run_batch([ROW], llm, engine, 'v1')

    assert stats['errors'] == 1
    with engine.connect() as conn:
        rows = _rows(conn)
    assert rows[0]['is_av_at_fault'] is None
    assert rows[0]['short_explanation_of_decision'] == judge_batch.ERROR_SENTINEL_TEXT


def test_rerun_same_version_upserts_no_duplicate(engine, tmp_path):
    first = StubClient(response=FaultVerdict(
        is_av_at_fault=False, av_fault_percentage=0.1,
        short_explanation_of_decision='Other party at fault.',
    ))
    judge_batch.run_batch(
        [ROW], CachedLLM(cache_dir=tmp_path / 'c1', _client=first), engine, 'v1')
    # Different cache dir + a different verdict forces a real second call; the
    # row count must stay at 1 (upsert), with the new value winning.
    second = StubClient(response=FaultVerdict(
        is_av_at_fault=True, av_fault_percentage=0.8,
        short_explanation_of_decision='Revised: AV at fault.',
    ))
    judge_batch.run_batch(
        [ROW], CachedLLM(cache_dir=tmp_path / 'c2', _client=second), engine, 'v1')

    with engine.connect() as conn:
        rows = _rows(conn)
    assert len(rows) == 1
    assert bool(rows[0]['is_av_at_fault']) is True
    assert float(rows[0]['av_fault_percentage']) == 0.8


def test_new_version_appends_alongside_old(engine, tmp_path):
    verdict = FaultVerdict(is_av_at_fault=True, av_fault_percentage=0.5,
                           short_explanation_of_decision='Shared fault.')
    judge_batch.run_batch(
        [ROW], CachedLLM(cache_dir=tmp_path / 'c1', _client=StubClient(verdict)),
        engine, 'v1')
    judge_batch.run_batch(
        [ROW], CachedLLM(cache_dir=tmp_path / 'c2', _client=StubClient(verdict)),
        engine, 'v2')
    with engine.connect() as conn:
        rows = _rows(conn)
    assert {r['fault_version'] for r in rows} == {'v1', 'v2'}


def test_content_addressed_cache_avoids_second_llm_call(engine, tmp_path):
    verdict = FaultVerdict(is_av_at_fault=True, av_fault_percentage=0.7,
                           short_explanation_of_decision='AV at fault.')
    cache = tmp_path / 'cache'

    first_stub = StubClient(response=verdict)
    llm1 = CachedLLM(cache_dir=cache, _client=first_stub)
    judge_batch.run_batch([ROW], llm1, engine, 'v1')
    assert llm1.stats['llm_calls'] == 1

    # A fresh CachedLLM over the same cache dir + same row -> cache hit, the
    # stub is never invoked again.
    second_stub = StubClient(response=None)  # would raise if called
    llm2 = CachedLLM(cache_dir=cache, _client=second_stub)
    judge_batch.run_batch([ROW], llm2, engine, 'v2')
    assert llm2.stats['cache_hits'] == 1
    assert llm2.stats['llm_calls'] == 0
    assert second_stub.calls == []


def test_dry_run_writes_nothing(engine, tmp_path):
    llm = CachedLLM(cache_dir=tmp_path / 'cache', dry_run=True,
                    _client=StubClient(response=None))
    stats = judge_batch.run_batch([ROW], llm, engine, 'v1')
    assert stats['written'] == 0
    assert stats['dry_run_skipped'] == 1
    with engine.connect() as conn:
        assert _rows(conn) == []
