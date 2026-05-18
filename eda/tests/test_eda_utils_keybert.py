'''Light tests for eda_utils_keybert.

Real KeyBERT instantiation downloads sentence-transformers weights; we keep
pytest fast by injecting a stub ``KeyBERT`` model via the ``_kw_model``
seam. Semantic validation lives in the demo notebook.
'''
import numpy as np
import pytest


class StubKWModel:
    '''Records calls and returns predictable shapes.'''
    def __init__(self, vocab=('apple', 'banana', 'cherry'), word_dim=8):
        self.vocab = list(vocab)
        self.word_dim = word_dim
        self.embed_calls = []
        self.kw_calls = []

    def extract_embeddings(self, docs, **kwargs):
        self.embed_calls.append({'docs': list(docs), 'kwargs': dict(kwargs)})
        doc_emb = np.zeros((len(docs), self.word_dim))  # unused by tests
        word_emb = np.zeros((len(self.vocab), self.word_dim))
        return doc_emb, word_emb

    def extract_keywords(self, docs, **kwargs):
        self.kw_calls.append({'docs': list(docs), 'kwargs': dict(kwargs)})
        return [
            [(self.vocab[0], 0.9), (self.vocab[1], 0.6)] for _ in docs
        ]


def test_row_mismatch_raises_value_error():
    from eda_utils_keybert import keybert_per_doc
    texts = ['a', 'b', 'c']
    doc_emb = np.zeros((2, 8))
    with pytest.raises(ValueError, match='doc_embeddings'):
        keybert_per_doc(texts, doc_emb, _kw_model=StubKWModel())


def test_1d_doc_embeddings_raises():
    from eda_utils_keybert import keybert_per_doc
    with pytest.raises(ValueError, match='2D'):
        keybert_per_doc(['a'], np.zeros(8), _kw_model=StubKWModel())


def test_passes_embeddings_and_vectorizer_args_through():
    from eda_utils_keybert import keybert_per_doc
    stub = StubKWModel()
    texts = ['alpha', 'beta']
    doc_emb = np.arange(2 * 8).reshape(2, 8).astype(np.float32)
    df = keybert_per_doc(
        texts, doc_emb, top_k=5,
        keyphrase_ngram_range=(1, 2), stop_words='english', min_df=2,
        _kw_model=stub,
    )

    assert len(stub.embed_calls) == 1
    assert len(stub.kw_calls) == 1

    embed_kwargs = stub.embed_calls[0]['kwargs']
    kw_kwargs = stub.kw_calls[0]['kwargs']
    # KeyBERT invariant: vectorizer args identical between the two calls
    for key in ('keyphrase_ngram_range', 'stop_words', 'min_df'):
        assert embed_kwargs[key] == kw_kwargs[key], (
            f'vectorizer arg {key!r} drifted between extract_embeddings and '
            f'extract_keywords'
        )

    # Our externally-computed doc_embeddings were forwarded verbatim
    np.testing.assert_array_equal(kw_kwargs['doc_embeddings'], doc_emb)
    assert kw_kwargs['word_embeddings'].shape[0] == 3  # stub vocab size

    assert list(df.columns) == ['doc_index', 'keyphrases']
    assert len(df) == 2
    assert df['keyphrases'].iloc[0] == [('apple', 0.9), ('banana', 0.6)]


def test_corpus_aggregates_per_doc_scores():
    from eda_utils_keybert import keybert_corpus
    stub = StubKWModel()
    texts = ['x', 'y', 'z']
    doc_emb = np.zeros((3, 8))
    df = keybert_corpus(texts, doc_emb, top_k=5, _kw_model=stub)

    assert list(df.columns) == ['phrase', 'score']
    assert df.iloc[0]['phrase'] == 'apple'
    # 3 docs * 0.9 each
    assert df.iloc[0]['score'] == pytest.approx(0.9 * 3)
    assert df.iloc[1]['phrase'] == 'banana'
    assert df.iloc[1]['score'] == pytest.approx(0.6 * 3)


def test_pandas_series_input_accepted():
    import pandas as pd
    from eda_utils_keybert import keybert_per_doc
    stub = StubKWModel()
    texts = pd.Series(['a', 'b'])
    doc_emb = np.zeros((2, 8))
    df = keybert_per_doc(texts, doc_emb, _kw_model=stub)
    assert len(df) == 2
