'''
EDA utils for basic NLP tasks (length stats, n-grams, tf-idf, word cloud).
'''
import pandas as pd
import matplotlib.pyplot as plt
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


def plot_word_cloud(series, max_words=150, stop_words='english',
                    width=900, height=450, ax=None, title=None):
    '''Render a word cloud from a text Series.  Requires the `wordcloud` package.'''
    try:
        from wordcloud import WordCloud, STOPWORDS
    except ImportError as e:
        raise ImportError(
            "plot_word_cloud requires the `wordcloud` package "
            "(uv pip install wordcloud)"
        ) from e

    text = ' '.join(series.dropna().astype(str).tolist())
    sw = set(STOPWORDS) if stop_words == 'english' else set(stop_words or [])
    wc = WordCloud(width=width, height=height, max_words=max_words,
                   stopwords=sw, background_color='white').generate(text)
    if ax is None:
        fig, ax = plt.subplots(figsize=(width / 100, height / 100))
    ax.imshow(wc, interpolation='bilinear')
    ax.axis('off')
    if title:
        ax.set_title(title)
    plt.tight_layout()
    return ax
