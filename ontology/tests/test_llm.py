'''Tests for llm.py — cache semantics, retries, dry-run. No network.'''
import json

import pytest
from pydantic import BaseModel

from llm import CachedLLM, LLMCallError, cache_key


class Toy(BaseModel):
    value: str


def make_llm(tmp_path, client, **kwargs):
    kwargs.setdefault('_sleep', lambda s: None)
    return CachedLLM(model_id='test-model', cache_dir=tmp_path,
                     _client=client, **kwargs)


def test_second_identical_call_is_cache_hit(tmp_path, stub_llm_factory):
    first_client = stub_llm_factory(responses=[Toy(value='a')])
    llm = make_llm(tmp_path, first_client)
    assert llm.call('prompt', Toy).value == 'a'

    second_client = stub_llm_factory()  # no responses queued: any call fails
    llm2 = make_llm(tmp_path, second_client)
    assert llm2.call('prompt', Toy).value == 'a'
    assert second_client.calls == []
    assert llm2.stats == {'cache_hits': 1, 'llm_calls': 0, 'retries': 0,
                          'dry_run_misses': 0}


def test_prompt_change_changes_cache_key(tmp_path, stub_llm_factory):
    client = stub_llm_factory(responses=[Toy(value='a'), Toy(value='b')])
    llm = make_llm(tmp_path, client)
    llm.call('prompt v1', Toy)
    llm.call('prompt v2', Toy)
    assert len(client.calls) == 2
    assert cache_key('prompt v1', 'm') != cache_key('prompt v2', 'm')


def test_model_change_changes_cache_key():
    assert cache_key('same prompt', 'model-a') != cache_key('same prompt', 'model-b')


def test_transient_failure_retries_then_succeeds(tmp_path, stub_llm_factory):
    client = stub_llm_factory(responses=[Toy(value='ok')], fail_first_n=2,
                              status=429)
    llm = make_llm(tmp_path, client, max_attempts=4)
    assert llm.call('p', Toy).value == 'ok'
    assert llm.stats['retries'] == 2
    assert len(client.calls) == 3


def test_permanent_failure_raises_after_max_attempts(tmp_path, stub_llm_factory):
    client = stub_llm_factory(fail_first_n=99, status=429)
    llm = make_llm(tmp_path, client, max_attempts=3)
    with pytest.raises(LLMCallError, match='3 attempt'):
        llm.call('p', Toy)
    assert len(client.calls) == 3


def test_non_transient_failure_raises_immediately(tmp_path, stub_llm_factory):
    client = stub_llm_factory(fail_first_n=99, status=400)
    llm = make_llm(tmp_path, client, max_attempts=4)
    with pytest.raises(LLMCallError):
        llm.call('p', Toy)
    assert len(client.calls) == 1  # no retry on a 400


def test_zero_retries_raises_not_none(tmp_path, stub_llm_factory):
    # The embeddings-pattern bug: max_retries=0 silently returned None.
    client = stub_llm_factory(fail_first_n=99, status=429)
    llm = make_llm(tmp_path, client, max_attempts=1)
    with pytest.raises(LLMCallError):
        llm.call('p', Toy)


def test_none_result_raises_not_propagates(tmp_path, stub_llm_factory):
    client = stub_llm_factory(responses=[None])
    llm = make_llm(tmp_path, client)
    with pytest.raises(LLMCallError, match='no parseable'):
        llm.call('p', Toy)


def test_interrupt_keeps_completed_calls_persisted(tmp_path, stub_llm_factory):
    # Docs 1-2 succeed, doc 3 fails permanently: the first two cache files
    # must already be on disk (incremental, not end-of-run, persistence).
    client = stub_llm_factory(responses=[Toy(value='1'), Toy(value='2')])
    llm = make_llm(tmp_path, client)
    llm.call('doc 1', Toy)
    llm.call('doc 2', Toy)
    with pytest.raises(LLMCallError):  # stub out of responses = the "crash"
        llm.call('doc 3', Toy)

    cached = list(tmp_path.rglob('*.json'))
    assert len(cached) == 2
    resumed = make_llm(tmp_path, stub_llm_factory(responses=[Toy(value='3')]))
    assert resumed.call('doc 1', Toy).value == '1'
    assert resumed.call('doc 3', Toy).value == '3'
    assert resumed.stats['cache_hits'] == 1
    assert resumed.stats['llm_calls'] == 1


def test_dry_run_counts_misses_without_calling(tmp_path, stub_llm_factory):
    client = stub_llm_factory(responses=[Toy(value='a')])
    make_llm(tmp_path, client).call('cached prompt', Toy)

    dry_client = stub_llm_factory()
    llm = make_llm(tmp_path, dry_client, dry_run=True)
    assert llm.call('cached prompt', Toy).value == 'a'   # hits still served
    assert llm.call('new prompt', Toy) is None
    assert dry_client.calls == []
    assert llm.stats['cache_hits'] == 1
    assert llm.stats['dry_run_misses'] == 1


def test_cache_file_records_model_and_key(tmp_path, stub_llm_factory):
    client = stub_llm_factory(responses=[Toy(value='a')])
    llm = make_llm(tmp_path, client)
    llm.call('p', Toy)
    payload = json.loads(next(tmp_path.rglob('*.json')).read_text(encoding='utf-8'))
    assert payload['model_id'] == 'test-model'
    assert payload['cache_key'] == cache_key('p', 'test-model')
    assert payload['result'] == {'value': 'a'}


def test_max_attempts_below_one_rejected(tmp_path):
    with pytest.raises(ValueError):
        CachedLLM(cache_dir=tmp_path, max_attempts=0)


def test_connection_errors_are_transient(tmp_path, stub_llm_factory):
    # anthropic.APIConnectionError-shaped failures carry no status_code and
    # no 'timeout' in the class name; long batch runs must retry through.
    from llm import is_transient

    class APIConnectionError(Exception):
        pass

    assert is_transient(APIConnectionError('reset by peer'))
    assert is_transient(ConnectionError('builtin'))
    assert is_transient(TimeoutError())
    assert not is_transient(ValueError('permanent'))

    client = stub_llm_factory(responses=[Toy(value='ok')])
    original_invoke = client.invoke
    calls = {'n': 0}

    def flaky_invoke(prompt, schema):
        calls['n'] += 1
        if calls['n'] == 1:
            raise APIConnectionError('connection reset')
        return original_invoke(prompt, schema)

    client.invoke = flaky_invoke
    llm = make_llm(tmp_path, client, max_attempts=3)
    assert llm.call('p', Toy).value == 'ok'
    assert llm.stats['retries'] == 1
