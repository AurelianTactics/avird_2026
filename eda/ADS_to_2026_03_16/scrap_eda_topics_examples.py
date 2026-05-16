'''
Example usage for eda_utils_topics.

All four pipelines return `(topics_df, doc_topic, doc_index)`:
* topics_df  -- one row per topic; `top_words` is a comma-joined str,
                `top_weights` is a list of L1-normalized weights
                (comparable across all four pipelines).
* doc_topic  -- ndarray (n_docs, n_topics), positional rows.
* doc_index  -- pandas Index of rows that survived NaN-drop; use it to
                join doc_topic back to the original DataFrame.

Run from `eda/ADS_to_2026_03_16/` after loading and treating your data
into `ads_df` and `narratives = ads_df['<narrative_col>']`.
'''
import sys
sys.path.append('..')

import numpy as np
import pandas as pd

from eda_utils_topics import lda_sklearn, nmf_sklearn, lda_gensim, nmf_gensim


# ---------------------------------------------------------------------------
# Assume `ads_df` and `narratives` are already loaded / treated.
# ---------------------------------------------------------------------------
# ads_df = ...
# narratives = ads_df['Narrative']


# ---------------------------------------------------------------------------
# 1) CountVectorizer -> sklearn LatentDirichletAllocation
# ---------------------------------------------------------------------------
topics_df, doc_topic, doc_index = lda_sklearn(
    narratives,
    n_topics=8,
    top_n_words=12,
    min_df=5,
    max_df=0.9,
    # learning_method='batch' is the default; switch to 'online' for huge corpora.
)
print('lda_sklearn topics_df:', topics_df.shape, 'doc_topic:', doc_topic.shape)
print(topics_df)

# Assign dominant topic back to ads_df by doc_index.
dominant = pd.Series(doc_topic.argmax(axis=1), index=doc_index,
                     name='lda_sklearn_topic')
ads_df_topics = ads_df.join(dominant)
print(ads_df_topics['lda_sklearn_topic'].value_counts(dropna=False).head())


# ---------------------------------------------------------------------------
# 2) TfidfVectorizer -> sklearn NMF
# ---------------------------------------------------------------------------
topics_df, doc_topic, doc_index = nmf_sklearn(
    narratives,
    n_topics=8,
    top_n_words=12,
    min_df=5,
    max_df=0.9,
)
print('nmf_sklearn topics_df:', topics_df.shape)
print(topics_df)

# Full per-doc topic-weight DataFrame indexed back to the original rows.
doc_topic_df = pd.DataFrame(
    doc_topic,
    index=doc_index,
    columns=[f'nmf_topic_{k}' for k in range(doc_topic.shape[1])],
)
print(doc_topic_df.head())


# ---------------------------------------------------------------------------
# 3) Tokenize -> gensim LdaModel  (requires `uv pip install gensim`)
# ---------------------------------------------------------------------------
topics_df, doc_topic, doc_index = lda_gensim(
    narratives,
    n_topics=8,
    top_n_words=12,
    no_below=5,
    no_above=0.9,
    passes=10,
)
print('lda_gensim topics_df:', topics_df.shape)
print(topics_df)

# top_weights is a list-in-cell; expand a row to see word + weight pairs.
row = topics_df.iloc[0]
print(list(zip(row['top_words'].split(', '), row['top_weights'])))


# ---------------------------------------------------------------------------
# 4) Tokenize + TF-IDF -> gensim Nmf  (requires gensim)
# ---------------------------------------------------------------------------
topics_df, doc_topic, doc_index = nmf_gensim(
    narratives,
    n_topics=8,
    top_n_words=12,
    no_below=5,
    no_above=0.9,
    passes=10,
)
print('nmf_gensim topics_df:', topics_df.shape)
print(topics_df)


# ---------------------------------------------------------------------------
# Tips
# ---------------------------------------------------------------------------
# Custom stopwords on top of sklearn's English defaults:
#   from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
#   sw = set(ENGLISH_STOP_WORDS) | {'vehicle', 'av', 'driver', 'incident'}
#   lda_sklearn(narratives, stop_words=list(sw))
#
# N-grams (sklearn only): lda_sklearn(narratives, ngram_range=(1, 2))
#
# Tiny corpus / vocab fully filtered: relax min_df/no_below (1) and
# max_df/no_above (1.0). The pipelines raise ValueError with an
# actionable message rather than crashing inside the library.
#
# Reproducibility: all four accept `random_state` (default 0).
