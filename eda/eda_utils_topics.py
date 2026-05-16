'''
EDA utils for topic modeling on narrative text.

Four pipelines:
* lda_sklearn   - CountVectorizer  -> sklearn LatentDirichletAllocation
* lda_gensim    - tokenize         -> gensim LdaModel
* nmf_sklearn   - TfidfVectorizer  -> sklearn NMF
* nmf_gensim    - tokenize + tfidf -> gensim Nmf

All four take a pandas Series of (treated) narrative text and return:
  topics_df : DataFrame with one row per topic. `top_words` is a comma-joined
              string for display; `top_weights` is a list of L1-normalized
              weights per word, so values are comparable across all four
              pipelines.
  doc_topic : ndarray of shape (n_docs, n_topics) with topic weights.
  doc_index : the pandas Index of rows that survived NaN-drop. Row i of
              doc_topic corresponds to doc_index[i] in the original Series, so
              callers can rebuild an aligned Series via
                  pd.Series(doc_topic[:, k], index=doc_index)
              or join back to the original DataFrame on doc_index.
'''
import re
import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.decomposition import LatentDirichletAllocation, NMF


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _clean_series(series):
    s = series.dropna().astype(str)
    if len(s) == 0:
        raise ValueError('series is empty after dropping NaN')
    return s


def _topics_df_from_components(components, feature_names, top_n_words):
    '''Build a tidy topics DataFrame from a sklearn (n_topics, n_features) matrix.

    Each row of `components` is L1-normalized so `top_weights` is a probability
    distribution comparable to gensim's `show_topic` output.
    '''
    n = min(top_n_words, len(feature_names))
    rows = []
    for topic_idx, weights in enumerate(components):
        total = float(weights.sum())
        norm = weights / total if total > 0 else weights
        top_idx = np.argsort(norm)[::-1][:n]
        rows.append({
            'topic': topic_idx,
            'top_words': ', '.join(feature_names[i] for i in top_idx),
            'top_weights': [float(norm[i]) for i in top_idx],
        })
    return pd.DataFrame(rows)


def _topics_df_from_gensim_model(model, n_topics, top_n_words):
    '''Build a tidy topics DataFrame from a gensim LdaModel or Nmf.'''
    rows = []
    for topic_idx in range(n_topics):
        terms = model.show_topic(topic_idx, topn=top_n_words)
        rows.append({
            'topic': topic_idx,
            'top_words': ', '.join(w for w, _ in terms),
            'top_weights': [float(p) for _, p in terms],
        })
    return pd.DataFrame(rows)


def _simple_tokenize(text, stop_words=None):
    '''Lowercase + alpha-token split. `stop_words` should be a set or None.'''
    tokens = re.findall(r"[A-Za-z][A-Za-z\-']+", text.lower())
    if stop_words is not None:
        tokens = [t for t in tokens if t not in stop_words]
    return tokens


def _build_stopword_set(stop_words):
    '''Resolve a stop_words param to a set (or None) for gensim pipelines.

    Accepts the literal string `'english'`, a list/set/frozenset of tokens, or
    None. Any other string is rejected -- silently iterating its characters as
    a stopword set would be a footgun.
    '''
    if stop_words is None:
        return None
    if stop_words == 'english':
        from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
        return set(ENGLISH_STOP_WORDS)
    if isinstance(stop_words, str):
        raise ValueError(
            f"stop_words={stop_words!r} not supported; pass 'english', a "
            "collection of tokens, or None"
        )
    return set(stop_words)


# ---------------------------------------------------------------------------
# sklearn pipelines
# ---------------------------------------------------------------------------
def lda_sklearn(series, n_topics=10, top_n_words=10, stop_words='english',
                min_df=2, max_df=0.95, ngram_range=(1, 1), random_state=0,
                max_iter=20, learning_method='batch'):
    '''CountVectorizer -> sklearn LatentDirichletAllocation.'''
    s = _clean_series(series)
    vec = CountVectorizer(stop_words=stop_words, min_df=min_df, max_df=max_df,
                          ngram_range=ngram_range)
    X = vec.fit_transform(s)
    lda = LatentDirichletAllocation(n_components=n_topics, max_iter=max_iter,
                                    learning_method=learning_method,
                                    random_state=random_state)
    doc_topic = lda.fit_transform(X)
    topics_df = _topics_df_from_components(
        lda.components_, vec.get_feature_names_out(), top_n_words
    )
    return topics_df, doc_topic, s.index


def nmf_sklearn(series, n_topics=10, top_n_words=10, stop_words='english',
                min_df=2, max_df=0.95, ngram_range=(1, 1), random_state=0,
                max_iter=400):
    '''TfidfVectorizer -> sklearn NMF.'''
    s = _clean_series(series)
    vec = TfidfVectorizer(stop_words=stop_words, min_df=min_df, max_df=max_df,
                          ngram_range=ngram_range)
    X = vec.fit_transform(s)
    nmf = NMF(n_components=n_topics, init='nndsvd', max_iter=max_iter,
              random_state=random_state)
    doc_topic = nmf.fit_transform(X)
    topics_df = _topics_df_from_components(
        nmf.components_, vec.get_feature_names_out(), top_n_words
    )
    return topics_df, doc_topic, s.index


# ---------------------------------------------------------------------------
# gensim pipelines
# ---------------------------------------------------------------------------
def lda_gensim(series, n_topics=10, top_n_words=10, stop_words='english',
               no_below=2, no_above=0.95, random_state=0, passes=10):
    '''Tokenize -> gensim LdaModel (uses bag-of-words counts).'''
    try:
        from gensim.corpora import Dictionary
        from gensim.models import LdaModel
    except ImportError as e:
        raise ImportError(
            "lda_gensim requires the `gensim` package (uv pip install gensim)"
        ) from e

    sw = _build_stopword_set(stop_words)
    s = _clean_series(series)
    docs = [_simple_tokenize(t, stop_words=sw) for t in s]

    dictionary = Dictionary(docs)
    dictionary.filter_extremes(no_below=no_below, no_above=no_above)
    if len(dictionary) == 0:
        raise ValueError(
            'dictionary is empty after filter_extremes; relax no_below/no_above'
        )
    corpus = [dictionary.doc2bow(d) for d in docs]

    model = LdaModel(corpus=corpus, id2word=dictionary, num_topics=n_topics,
                     passes=passes, random_state=random_state)
    topics_df = _topics_df_from_gensim_model(model, n_topics, top_n_words)

    doc_topic = np.zeros((len(corpus), n_topics), dtype=float)
    for i, bow in enumerate(corpus):
        for t, p in model.get_document_topics(bow, minimum_probability=0.0):
            doc_topic[i, t] = p
    return topics_df, doc_topic, s.index


def nmf_gensim(series, n_topics=10, top_n_words=10, stop_words='english',
               no_below=2, no_above=0.95, random_state=0, passes=10):
    '''Tokenize + TF-IDF -> gensim Nmf.'''
    try:
        from gensim.corpora import Dictionary
        from gensim.models import TfidfModel
        from gensim.models.nmf import Nmf
    except ImportError as e:
        raise ImportError(
            "nmf_gensim requires the `gensim` package (uv pip install gensim)"
        ) from e

    sw = _build_stopword_set(stop_words)
    s = _clean_series(series)
    docs = [_simple_tokenize(t, stop_words=sw) for t in s]

    dictionary = Dictionary(docs)
    dictionary.filter_extremes(no_below=no_below, no_above=no_above)
    if len(dictionary) == 0:
        raise ValueError(
            'dictionary is empty after filter_extremes; relax no_below/no_above'
        )
    bow_corpus = [dictionary.doc2bow(d) for d in docs]

    tfidf = TfidfModel(bow_corpus)
    tfidf_corpus = [tfidf[bow] for bow in bow_corpus]

    model = Nmf(corpus=tfidf_corpus, id2word=dictionary, num_topics=n_topics,
                passes=passes, random_state=random_state)
    topics_df = _topics_df_from_gensim_model(model, n_topics, top_n_words)

    doc_topic = np.zeros((len(tfidf_corpus), n_topics), dtype=float)
    for i, vec in enumerate(tfidf_corpus):
        for t, p in model[vec]:
            doc_topic[i, t] = p
    return topics_df, doc_topic, s.index
