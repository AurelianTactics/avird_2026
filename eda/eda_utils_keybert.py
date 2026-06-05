'''
EDA utils - KeyBERT keyword / keyphrase extraction over precomputed embeddings.

KeyBERT computes candidate words/phrases via a CountVectorizer, embeds them
with its own encoder, and ranks them by cosine similarity to the doc
embedding. We feed it our externally-computed doc embeddings via
``extract_keywords(doc_embeddings=...)`` so no docs are re-encoded; only the
small candidate-phrase vocabulary is encoded locally.

Documented KeyBERT invariant: the ``keyphrase_ngram_range`` / ``stop_words``
/ ``min_df`` args passed to ``extract_embeddings`` and ``extract_keywords``
must match, otherwise the precomputed embeddings line up with the wrong
candidate vocabulary. This module funnels both calls through one local
``vectorizer_kwargs`` dict to keep them in sync.

Public functions
----------------
* ``keybert_per_doc(texts, doc_embeddings, ...)`` -> DataFrame
    One row per input doc with a ``keyphrases`` list column of
    ``[(phrase, score), ...]`` tuples, sorted desc by score.

* ``keybert_corpus(texts, doc_embeddings, ...)`` -> DataFrame
    Top-N corpus-level keyphrases aggregated from per-doc scores.
'''
from collections import defaultdict

import numpy as np
import pandas as pd


DEFAULT_MODEL_ID = 'BAAI/bge-base-en-v1.5'
DEFAULT_KEYPHRASE_NGRAM_RANGE = (1, 3)
DEFAULT_STOP_WORDS = 'english'


def keybert_per_doc(
    texts,
    doc_embeddings,
    model_id=DEFAULT_MODEL_ID,
    top_k=10,
    keyphrase_ngram_range=DEFAULT_KEYPHRASE_NGRAM_RANGE,
    stop_words=DEFAULT_STOP_WORDS,
    min_df=1,
    use_mmr=True,
    diversity=0.5,
    _kw_model=None,
):
    '''Per-doc keyphrase extraction over precomputed embeddings.

    Parameters
    ----------
    texts : Sequence[str] or pd.Series
        Document texts. Row order must match ``doc_embeddings``.
    doc_embeddings : np.ndarray  shape (n_docs, dim)
        Precomputed doc embeddings (from ``eda_utils_embed.embed_texts``).
    model_id : str
        Sentence-transformers model id KeyBERT should load to encode the
        candidate-phrase vocabulary. Should match the encoder that produced
        ``doc_embeddings`` so doc and candidate vectors live in the same space.
    top_k : int
        Phrases per doc.
    keyphrase_ngram_range, stop_words, min_df :
        CountVectorizer args. Forwarded identically to both
        ``extract_embeddings`` and ``extract_keywords`` (KeyBERT invariant).
    use_mmr, diversity :
        MMR diversification controls.
    _kw_model :
        Test seam. Inject a stand-in for ``keybert.KeyBERT``.

    Returns
    -------
    DataFrame with columns ``doc_index`` (int) and ``keyphrases``
    (list of (phrase, score) tuples).
    '''
    docs = _as_list(texts)
    _validate_alignment(docs, doc_embeddings)

    kw_model = _kw_model if _kw_model is not None else _make_kw_model(model_id)
    vectorizer_kwargs = dict(
        keyphrase_ngram_range=keyphrase_ngram_range,
        stop_words=stop_words,
        min_df=min_df,
    )
    _, word_embeddings = kw_model.extract_embeddings(docs, **vectorizer_kwargs)
    keywords = kw_model.extract_keywords(
        docs,
        doc_embeddings=doc_embeddings,
        word_embeddings=word_embeddings,
        top_n=top_k,
        use_mmr=use_mmr,
        diversity=diversity,
        **vectorizer_kwargs,
    )

    rows = [{'doc_index': i, 'keyphrases': kp} for i, kp in enumerate(keywords)]
    return pd.DataFrame(rows)


def keybert_corpus(
    texts,
    doc_embeddings,
    model_id=DEFAULT_MODEL_ID,
    top_k=30,
    per_doc_k=30,
    keyphrase_ngram_range=DEFAULT_KEYPHRASE_NGRAM_RANGE,
    stop_words=DEFAULT_STOP_WORDS,
    min_df=1,
    use_mmr=True,
    diversity=0.5,
    _kw_model=None,
):
    '''Top-N corpus-level keyphrases aggregated from per-doc scores.

    Each per-doc phrase contributes its score; corpus score is the sum
    across docs. Phrases that appear in many docs with high scores rise to
    the top.

    Returns
    -------
    DataFrame with columns ``phrase`` (str) and ``score`` (float).
    '''
    per_doc = keybert_per_doc(
        texts, doc_embeddings,
        model_id=model_id, top_k=per_doc_k,
        keyphrase_ngram_range=keyphrase_ngram_range,
        stop_words=stop_words, min_df=min_df,
        use_mmr=use_mmr, diversity=diversity,
        _kw_model=_kw_model,
    )
    totals = defaultdict(float)
    for phrases in per_doc['keyphrases']:
        for phrase, score in phrases:
            totals[phrase] += float(score)
    items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:top_k]
    return pd.DataFrame(items, columns=['phrase', 'score'])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _as_list(texts):
    if isinstance(texts, pd.Series):
        return texts.tolist()
    return list(texts)


def _validate_alignment(docs, doc_embeddings):
    arr = np.asarray(doc_embeddings)
    if arr.ndim != 2:
        raise ValueError(
            f'doc_embeddings must be 2D, got ndim={arr.ndim} shape={arr.shape}'
        )
    if arr.shape[0] != len(docs):
        raise ValueError(
            f'doc_embeddings has {arr.shape[0]} rows but len(texts)={len(docs)}'
        )


def _make_kw_model(model_id):
    try:
        from keybert import KeyBERT
    except ImportError as e:
        raise ImportError(
            'keybert_* requires keybert (uv pip install keybert).'
        ) from e
    return KeyBERT(model=model_id)
