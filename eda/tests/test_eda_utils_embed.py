'''Tests for eda_utils_embed: cache + batch + retry logic via stub client.'''
import numpy as np
import pandas as pd
import pytest

from eda_utils_embed import embed_texts, _text_hash, _cache_path


def test_happy_path_returns_aligned_matrix(tmp_path, stub_client_factory):
    texts = pd.Series(['alpha', 'beta', 'gamma', 'delta', 'epsilon'])
    client = stub_client_factory(dim=8)
    emb, idx = embed_texts(
        texts, cache_dir=tmp_path, dataset_id='t', _client=client,
    )
    assert emb.shape == (5, 8)
    assert emb.dtype == np.float32
    assert idx.tolist() == list(range(5))
    assert np.isfinite(emb).all()
    assert len(client.calls) == 5


def test_drops_nan_and_whitespace_preserves_index(tmp_path, stub_client_factory):
    texts = pd.Series(
        ['real text', None, '   ', '', 'another'],
        index=[10, 11, 12, 13, 14],
    )
    client = stub_client_factory(dim=4)
    emb, idx = embed_texts(
        texts, cache_dir=tmp_path, dataset_id='t', _client=client,
    )
    assert emb.shape == (2, 4)
    assert idx.tolist() == [10, 14]
    assert client.calls == ['real text', 'another']


def test_cache_hit_zero_api_calls(tmp_path, stub_client_factory):
    texts = pd.Series(['one', 'two', 'three'])
    first = stub_client_factory(dim=4)
    emb1, _ = embed_texts(texts, cache_dir=tmp_path, dataset_id='t', _client=first)
    assert len(first.calls) == 3

    second = stub_client_factory(dim=4)
    emb2, _ = embed_texts(texts, cache_dir=tmp_path, dataset_id='t', _client=second)
    assert second.calls == []
    np.testing.assert_array_equal(emb1, emb2)


def test_cache_file_created_under_model_slug(tmp_path, stub_client_factory):
    cache_dir = tmp_path / 'nested' / 'embeddings'
    embed_texts(
        pd.Series(['hello']),
        cache_dir=cache_dir, dataset_id='smoke',
        _client=stub_client_factory(dim=4),
    )
    expected = cache_dir / 'BAAI__bge-base-en-v1.5' / 'smoke.parquet'
    assert expected.exists()


def test_partial_cache_hit_only_embeds_new(tmp_path, stub_client_factory):
    base = pd.Series(['x', 'y'])
    embed_texts(base, cache_dir=tmp_path, dataset_id='t',
                _client=stub_client_factory(dim=4))

    bigger = pd.Series(['x', 'y', 'z'])
    second = stub_client_factory(dim=4)
    emb, _ = embed_texts(bigger, cache_dir=tmp_path, dataset_id='t', _client=second)
    assert second.calls == ['z']
    assert emb.shape == (3, 4)
    # 'x' and 'y' came from cache; their vectors must match the second-run
    # values for 'z' on the same dim.
    assert np.isfinite(emb).all()


def test_duplicate_input_text_calls_api_once(tmp_path, stub_client_factory):
    texts = pd.Series(['same', 'same', 'same', 'different'])
    client = stub_client_factory(dim=4)
    emb, _ = embed_texts(texts, cache_dir=tmp_path, dataset_id='t', _client=client)
    assert len(client.calls) == 2  # unique hashes
    # All three 'same' rows have identical vectors
    np.testing.assert_array_equal(emb[0], emb[1])
    np.testing.assert_array_equal(emb[1], emb[2])
    assert not np.array_equal(emb[0], emb[3])


def test_missing_hf_token_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.delenv('HF_TOKEN', raising=False)
    # Force re-evaluation of the env even if .env populated it at import time.
    with pytest.raises(RuntimeError, match='HF_TOKEN'):
        embed_texts(pd.Series(['hi']), cache_dir=tmp_path, dataset_id='t')


def test_transient_retries_then_succeeds(tmp_path, stub_client_factory):
    client = stub_client_factory(dim=4, fail_first_n=2, status=429)
    emb, _ = embed_texts(
        pd.Series(['retryable']),
        cache_dir=tmp_path, dataset_id='t',
        max_retries=5, backoff_base=0.0, _client=client,
    )
    assert emb.shape == (1, 4)
    assert len(client.calls) == 3  # 2 fails + 1 success


def test_transient_exhausts_retries_and_raises(tmp_path, stub_client_factory):
    client = stub_client_factory(dim=4, fail_first_n=10, status=500)
    with pytest.raises(RuntimeError, match='500'):
        embed_texts(
            pd.Series(['always fails']),
            cache_dir=tmp_path, dataset_id='t',
            max_retries=3, backoff_base=0.0, _client=client,
        )


def test_round_trip_via_disk(tmp_path, stub_client_factory):
    '''Equivalent of a second process reading the parquet cache.'''
    texts = pd.Series(['first', 'second'])
    embed_texts(texts, cache_dir=tmp_path, dataset_id='t',
                _client=stub_client_factory(dim=4))

    fresh = stub_client_factory(dim=4)
    emb, _ = embed_texts(texts, cache_dir=tmp_path, dataset_id='t', _client=fresh)
    assert fresh.calls == []
    assert emb.shape == (2, 4)


def test_text_hash_normalizes_whitespace():
    assert _text_hash('hello') == _text_hash('  hello  ')
    assert _text_hash('hello') == _text_hash('hello\n')
    assert _text_hash('hello') != _text_hash('Hello')
    assert _text_hash('hello world') != _text_hash('helloworld')


def test_cache_path_uses_model_slug():
    p = _cache_path('cache', 'BAAI/bge-base-en-v1.5', 'ds')
    assert str(p).replace('\\', '/').endswith(
        'cache/BAAI__bge-base-en-v1.5/ds.parquet'
    )
