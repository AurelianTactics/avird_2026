'''
EDA utils for basic NLP tasks (length stats, n-grams, tf-idf).
'''
import re
from collections import Counter

import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer


def describe_text_lengths(series):
    s = series.dropna().astype(str)
    char_len = s.str.len()
    word_len = s.str.split().str.len()
    out = pd.DataFrame({'char_len': char_len, 'word_len': word_len})
    print("Character length:")
    print(char_len.describe())
    print("\nWord length:")
    print(word_len.describe())
    return out


def top_ngrams(series, n=1, top_k=20, stop_words='english', min_df=1):
    s = series.dropna().astype(str)
    vec = CountVectorizer(ngram_range=(n, n), stop_words=stop_words, min_df=min_df)
    counts = vec.fit_transform(s)
    totals = counts.sum(axis=0).A1
    df = (
        pd.DataFrame({'ngram': vec.get_feature_names_out(), 'count': totals})
        .sort_values('count', ascending=False)
        .head(top_k)
        .reset_index(drop=True)
    )
    return df


def top_tfidf(series, n=1, top_k=20, stop_words='english', min_df=1, max_df=1.0):
    s = series.dropna().astype(str)
    vec = TfidfVectorizer(
        ngram_range=(1, n), stop_words=stop_words, min_df=min_df, max_df=max_df
    )
    tfidf = vec.fit_transform(s)
    means = tfidf.mean(axis=0).A1
    df = (
        pd.DataFrame({'term': vec.get_feature_names_out(), 'tfidf_mean': means})
        .sort_values('tfidf_mean', ascending=False)
        .head(top_k)
        .reset_index(drop=True)
    )
    return df
