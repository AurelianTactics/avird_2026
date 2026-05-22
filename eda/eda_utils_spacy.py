'''
EDA utils for spaCy-based narrative analysis.

Four capability groups, mirroring spaCy's core surface:

1. Linguistic features  -- tokens, POS, lemmas, sentence segmentation, noun chunks
2. Named Entity Recognition -- doc.ents + per-label counts and crosstabs
3. Rule-based matching  -- Matcher (token patterns) + PhraseMatcher (seed terms)
4. Word vectors / similarity -- token.similarity + doc.similarity (mean-pooled)

All public functions follow the eda_utils_*.py contract:
* take a pandas Series of treated narratives (or, for downstream helpers, the
  `docs` + `doc_index` produced by `parse_corpus`)
* return a DataFrame / list / dict the notebook can save without further shaping
* never modify the input in place

The `(result, doc_index)` shape from `eda_utils_topics` is preserved -- callers
join back to `treated_df` on `doc_index` to attach spaCy outputs to the
original rows.

Run from `eda/ADS_to_2026_03_16/` after sys.path.append('..'):
    import eda_utils_spacy
    nlp = eda_utils_spacy.load_nlp()
    docs, doc_index = eda_utils_spacy.parse_corpus(
        treated_df['Narrative'], nlp=nlp, cache_dir='artifacts_spacy/_docbin'
    )

Requires the avird-2026-eda-spacy sidecar env (Python 3.12, spaCy >= 3.8,
en_core_web_lg pinned in requirements.txt). The avird-2026-eda env on Python
3.14 will not work -- spaCy has no 3.14 wheels as of 2026-05.
'''
import functools
import hashlib
import random
import re
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
# SGO narrative redaction sentinels. Stripping these before NER prevents
# spaCy from fragmenting them into spurious ORG / PRODUCT entities.
_REDACTION_PATTERNS = [
    r'\[REDACTED,?\s*MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION\]',
    r'\[MAY CONTAIN CONFIDENTIAL BUSINESS INFORMATION\]',
    r'\[MAY CONTAIN PERSONALLY IDENTIFIABLE INFORMATION\]',
    r'\[REDACTED[^\]]*\]',
]
_REDACTION_REGEX = re.compile('|'.join(_REDACTION_PATTERNS), re.IGNORECASE)
_XXX_REGEX = re.compile(r'\bX{2,}\b')

# Default AV-corpus stopwords to layer on top of sklearn's English defaults.
# Same set called out in the eda_utils_topics tip block.
DEFAULT_EXTRA_STOPWORDS = ('av', 'vehicle', 'driver', 'incident', 'report')

# Seed phrases for the AV-domain PhraseMatcher in U7.
DEFAULT_AV_PHRASES = (
    'pickup truck',
    'parking lot',
    'left turn',
    'right turn',
    'intersection',
    'pedestrian',
    'bicycle',
    'cyclist',
    'autonomous mode',
    'manual mode',
    'rear-ended',
    'rear ended',
    'sideswipe',
    'merging',
    'crosswalk',
    'red light',
    'stop sign',
)


# ---------------------------------------------------------------------------
# U2 -- Model loader, preprocessing, stopwords
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=4)
def load_nlp(model_name='en_core_web_lg', disable=()):
    '''Load a spaCy model with `lru_cache` so notebook re-imports are cheap.

    `disable` is a tuple (hashable for the cache) of pipeline component names to
    skip at load time -- e.g. `disable=('parser',)`. v1 of this module keeps the
    full pipeline by default; the EDA wants everything.
    '''
    try:
        import spacy
    except ImportError as e:
        raise ImportError(
            'load_nlp requires spaCy. Activate the avird-2026-eda-spacy env: '
            'source ~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/'
            '.venv/Scripts/activate'
        ) from e
    return spacy.load(model_name, disable=list(disable))


def preprocess_narratives(series, replace_redaction='<REDACTED>', drop_xxx=False):
    '''Strip SGO redaction sentinels so they do not pollute spaCy NER.

    Returns a new Series aligned to the input index; NaN values pass through
    untouched (callers downstream drop them).

    Parameters
    ----------
    series : pandas.Series
        Raw narrative text.
    replace_redaction : str
        Replacement token for the long `[REDACTED, ...]` markers.
    drop_xxx : bool
        If True, also strip the standalone `XXX` redaction marker. Default
        False because `XXX` sometimes appears inside otherwise-meaningful
        spans (e.g., `intersection XXX at`) and dropping it can break
        sentence segmentation.
    '''
    def _clean(value):
        if pd.isna(value):
            return value
        text = str(value)
        text = _REDACTION_REGEX.sub(replace_redaction, text)
        if drop_xxx:
            text = _XXX_REGEX.sub('', text)
        # Collapse any whitespace runs the substitution left behind.
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    return series.map(_clean)


def build_stopwords(extra=DEFAULT_EXTRA_STOPWORDS):
    '''Return a set of stopwords extending sklearn's English defaults.

    Mirrors `_build_stopword_set` in eda_utils_topics so spaCy lemma filtering
    stays consistent with the topic-modeling pipelines.
    '''
    from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
    base = set(ENGLISH_STOP_WORDS)
    if extra:
        base |= {w.lower() for w in extra}
    return base


# ---------------------------------------------------------------------------
# U3 -- Cached corpus parsing via nlp.pipe + DocBin
# ---------------------------------------------------------------------------
def _hash_texts(texts):
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode('utf-8', errors='replace'))
        h.update(b'\x00')
    return h.hexdigest()[:16]


def parse_corpus(series, nlp=None, cache_dir=None, batch_size=64, n_process=1,
                 preprocess=True):
    '''Parse a narrative Series with `nlp.pipe`, caching results via DocBin.

    Returns
    -------
    docs : list[spacy.tokens.Doc]
        One Doc per non-NaN narrative, aligned positionally to `doc_index`.
    doc_index : pandas.Index
        The Series index of rows that survived NaN-drop. Use it to attach
        per-doc results back to the source DataFrame.

    Parameters
    ----------
    series : pandas.Series
        Raw or preprocessed narratives.
    nlp : spacy.language.Language, optional
        Loaded model. Defaults to `load_nlp()`.
    cache_dir : str | Path, optional
        Directory to store the DocBin cache. Filename embeds a content hash so
        changing the input invalidates the cache automatically. If None, parses
        in memory only.
    batch_size : int
        Forwarded to `nlp.pipe`.
    n_process : int
        Forwarded to `nlp.pipe`. Default 1 for Windows compatibility -- values
        > 1 require an `if __name__ == '__main__'` guard in scripts.
    preprocess : bool
        If True, run `preprocess_narratives` first to strip redaction sentinels.
    '''
    try:
        from spacy.tokens import DocBin
    except ImportError as e:
        raise ImportError(
            'parse_corpus requires spaCy. Activate avird-2026-eda-spacy.'
        ) from e

    if nlp is None:
        nlp = load_nlp()

    cleaned = preprocess_narratives(series) if preprocess else series
    cleaned = cleaned.dropna().astype(str)
    if len(cleaned) == 0:
        raise ValueError('series is empty after dropping NaN')

    texts = cleaned.tolist()
    doc_index = cleaned.index

    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        content_hash = _hash_texts(texts)
        cache_path = cache_dir / f'narratives_{content_hash}.spacy'
        if cache_path.exists():
            doc_bin = DocBin().from_disk(cache_path)
            docs = list(doc_bin.get_docs(nlp.vocab))
            if len(docs) == len(texts):
                return docs, doc_index
            # Stale / partial cache -- fall through and re-parse.

    docs = list(nlp.pipe(texts, batch_size=batch_size, n_process=n_process))

    if cache_path is not None:
        doc_bin = DocBin(store_user_data=False, docs=docs)
        doc_bin.to_disk(cache_path)

    return docs, doc_index


# ---------------------------------------------------------------------------
# U4 -- Linguistic features: tokens, POS, lemmas, sentence stats
# ---------------------------------------------------------------------------
def token_table(docs, doc_index, keep_pos=None, drop_stop=True, drop_punct=True,
                extra_stop=None, lowercase_lemma=True):
    '''Long-form token table: one row per kept token across all docs.

    Columns: doc_index, token, lemma, pos, tag, is_stop, is_punct.

    Parameters
    ----------
    keep_pos : iterable of str, optional
        If given, only tokens whose `.pos_` is in the set are kept.
    drop_stop : bool
        Drop spaCy-flagged stopwords (`token.is_stop`).
    drop_punct : bool
        Drop punctuation (`token.is_punct`).
    extra_stop : iterable of str, optional
        Extra lowercase lemmas to drop on top of spaCy's stoplist.
    '''
    if len(docs) != len(doc_index):
        raise ValueError(
            f'docs ({len(docs)}) and doc_index ({len(doc_index)}) length mismatch'
        )
    keep_pos = set(keep_pos) if keep_pos is not None else None
    extra = {w.lower() for w in extra_stop} if extra_stop else set()

    rows = []
    for idx, doc in zip(doc_index, docs):
        for tok in doc:
            if drop_punct and tok.is_punct:
                continue
            if drop_stop and tok.is_stop:
                continue
            if tok.is_space:
                continue
            lemma = tok.lemma_.lower() if lowercase_lemma else tok.lemma_
            if lemma in extra:
                continue
            if keep_pos is not None and tok.pos_ not in keep_pos:
                continue
            rows.append({
                'doc_index': idx,
                'token': tok.text,
                'lemma': lemma,
                'pos': tok.pos_,
                'tag': tok.tag_,
                'is_stop': bool(tok.is_stop),
                'is_punct': bool(tok.is_punct),
            })
    return pd.DataFrame(rows, columns=[
        'doc_index', 'token', 'lemma', 'pos', 'tag', 'is_stop', 'is_punct'
    ])


def top_lemmas_by_pos(docs, doc_index, pos='VERB', top_k=30, extra_stop=None,
                      lowercase=True):
    '''Top-K lemmas filtered by POS tag, with counts.'''
    tt = token_table(
        docs, doc_index, keep_pos=[pos], drop_stop=True, drop_punct=True,
        extra_stop=extra_stop, lowercase_lemma=lowercase,
    )
    if tt.empty:
        return pd.DataFrame(columns=['lemma', 'pos', 'count'])
    out = (
        tt.groupby('lemma').size().reset_index(name='count')
        .sort_values('count', ascending=False).head(top_k).reset_index(drop=True)
    )
    out['pos'] = pos
    return out[['lemma', 'pos', 'count']]


def sentence_stats(docs, doc_index):
    '''Per-document sentence stats: n_sentences, mean / max sentence length.'''
    rows = []
    for idx, doc in zip(doc_index, docs):
        sents = list(doc.sents)
        n = len(sents)
        if n == 0:
            rows.append({'doc_index': idx, 'n_sentences': 0,
                         'mean_sent_len_tokens': 0.0, 'max_sent_len_tokens': 0})
            continue
        lens = [len([t for t in s if not t.is_space]) for s in sents]
        rows.append({
            'doc_index': idx,
            'n_sentences': n,
            'mean_sent_len_tokens': float(np.mean(lens)) if lens else 0.0,
            'max_sent_len_tokens': int(max(lens)) if lens else 0,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# U5 -- Named Entity Recognition
# ---------------------------------------------------------------------------
def entity_table(docs, doc_index):
    '''Long-form NER table: one row per `doc.ents` span.

    Columns: doc_index, text, label, start_char, end_char.
    '''
    if len(docs) != len(doc_index):
        raise ValueError(
            f'docs ({len(docs)}) and doc_index ({len(doc_index)}) length mismatch'
        )
    rows = []
    for idx, doc in zip(doc_index, docs):
        for ent in doc.ents:
            rows.append({
                'doc_index': idx,
                'text': ent.text,
                'label': ent.label_,
                'start_char': ent.start_char,
                'end_char': ent.end_char,
            })
    return pd.DataFrame(rows, columns=[
        'doc_index', 'text', 'label', 'start_char', 'end_char'
    ])


def entity_counts_by_label(entity_df, label=None, top_k=20, lowercase=True):
    '''Per-label top-K table of entity texts.

    If `label` is given, returns just that label's top-K. If None, returns
    one frame with rows = (label, text, count) across the most-common labels.
    '''
    if entity_df.empty:
        return pd.DataFrame(columns=['label', 'text', 'count'])
    df = entity_df.copy()
    if lowercase:
        df['text'] = df['text'].str.lower()
    if label is not None:
        df = df[df['label'] == label]
        out = (df.groupby(['label', 'text']).size().reset_index(name='count')
                 .sort_values('count', ascending=False).head(top_k)
                 .reset_index(drop=True))
        return out
    # No label filter: top-K per label, stacked.
    grouped = (df.groupby(['label', 'text']).size().reset_index(name='count')
                 .sort_values(['label', 'count'], ascending=[True, False]))
    return (grouped.groupby('label', group_keys=False)
                   .head(top_k).reset_index(drop=True))


def org_vs_master_entity_crosstab(entity_df, treated_df,
                                   master_entity_col='master_entity',
                                   top_k_orgs=15, lowercase=True):
    '''Crosstab spaCy-extracted `ORG` entities against the treated `master_entity`.

    Joins on `doc_index` so the user can sanity-check whether spaCy ORG output
    tracks the curated reporter field.
    '''
    if master_entity_col not in treated_df.columns:
        raise KeyError(
            f'{master_entity_col!r} not in treated_df columns; '
            'check that apply_all_treatments has been run.'
        )
    if entity_df.empty:
        return pd.DataFrame()
    orgs = entity_df[entity_df['label'] == 'ORG'].copy()
    if orgs.empty:
        return pd.DataFrame()
    if lowercase:
        orgs['text'] = orgs['text'].str.lower()
    joined = orgs.merge(
        treated_df[[master_entity_col]],
        left_on='doc_index', right_index=True, how='left',
    )
    top_orgs = (joined.groupby('text').size()
                       .sort_values(ascending=False).head(top_k_orgs).index)
    joined_top = joined[joined['text'].isin(top_orgs)]
    return pd.crosstab(joined_top[master_entity_col], joined_top['text'])


# ---------------------------------------------------------------------------
# U6 -- Noun chunks
# ---------------------------------------------------------------------------
def noun_chunk_table(docs, doc_index, lowercase=True, drop_stop=True):
    '''Long-form noun-chunk table.

    Columns: doc_index, chunk_text, root_lemma, root_pos.
    '''
    rows = []
    for idx, doc in zip(doc_index, docs):
        for chunk in doc.noun_chunks:
            text = chunk.text.lower() if lowercase else chunk.text
            text = text.strip()
            if not text:
                continue
            if drop_stop:
                # Drop chunks made entirely of stopwords / punctuation.
                content = [t for t in chunk
                           if not t.is_stop and not t.is_punct and not t.is_space]
                if not content:
                    continue
            rows.append({
                'doc_index': idx,
                'chunk_text': text,
                'root_lemma': chunk.root.lemma_.lower() if lowercase else chunk.root.lemma_,
                'root_pos': chunk.root.pos_,
            })
    return pd.DataFrame(rows, columns=[
        'doc_index', 'chunk_text', 'root_lemma', 'root_pos'
    ])


def top_noun_chunks(docs, doc_index, top_k=30, lowercase=True, drop_stop=True,
                    extra_stop=None):
    '''Top-K noun chunks by raw count.'''
    nc = noun_chunk_table(docs, doc_index, lowercase=lowercase, drop_stop=drop_stop)
    if nc.empty:
        return pd.DataFrame(columns=['chunk_text', 'count'])
    extra = {w.lower() for w in extra_stop} if extra_stop else set()
    if extra:
        nc = nc[~nc['chunk_text'].isin(extra)]
    return (nc.groupby('chunk_text').size().reset_index(name='count')
              .sort_values('count', ascending=False).head(top_k)
              .reset_index(drop=True))


# ---------------------------------------------------------------------------
# U7 -- Rule-based matching: Matcher + PhraseMatcher
# ---------------------------------------------------------------------------
def build_av_phrase_matcher(nlp, phrases=DEFAULT_AV_PHRASES, attr='LOWER',
                            label='AV_PHRASE'):
    '''Build a `PhraseMatcher` seeded with curated AV-domain phrases.

    All phrases share a single label so callers see one count per phrase
    string via `apply_matcher`; switch to per-phrase labels if you need to
    distinguish them at match-time.
    '''
    try:
        from spacy.matcher import PhraseMatcher
    except ImportError as e:
        raise ImportError('build_av_phrase_matcher requires spaCy.') from e
    matcher = PhraseMatcher(nlp.vocab, attr=attr)
    patterns = [nlp.make_doc(p) for p in phrases]
    matcher.add(label, patterns)
    return matcher


# Default token-pattern set for the maneuver Matcher. Listed at module scope
# so the labels are stable and callers can reference them when filtering.
DEFAULT_MANEUVER_PATTERNS = {
    'TURNING_LEFT': [[{'LOWER': 'turning'}, {'LOWER': 'left'}]],
    'TURNING_RIGHT': [[{'LOWER': 'turning'}, {'LOWER': 'right'}]],
    'STOPPED_AT_INTERSECTION': [[
        {'LEMMA': 'stop'}, {'LOWER': 'at'}, {'LOWER': 'the', 'OP': '?'},
        {'LOWER': 'intersection'},
    ]],
    'REAR_ENDED': [[
        {'LOWER': {'IN': ['rear-ended', 'rear', 'rear-end']}},
        {'LOWER': 'ended', 'OP': '?'},
    ]],
    'CHANGING_LANES': [[{'LOWER': {'IN': ['changing', 'changed']}},
                         {'LOWER': 'lanes'}]],
}


def build_maneuver_matcher(nlp, patterns=None):
    '''Build a `Matcher` with token patterns labelled by maneuver name.

    `patterns` is a `{label: [pattern, ...]}` dict; defaults to
    DEFAULT_MANEUVER_PATTERNS.
    '''
    try:
        from spacy.matcher import Matcher
    except ImportError as e:
        raise ImportError('build_maneuver_matcher requires spaCy.') from e
    matcher = Matcher(nlp.vocab)
    patterns = patterns if patterns is not None else DEFAULT_MANEUVER_PATTERNS
    for label, pats in patterns.items():
        matcher.add(label, pats)
    return matcher


def _matcher_is_empty(matcher):
    try:
        return len(matcher) == 0
    except TypeError:
        return False


def apply_matcher(docs, doc_index, matcher, nlp=None):
    '''Apply a Matcher or PhraseMatcher across `docs`.

    Returns a long-form DataFrame [doc_index, pattern_label, span_text,
    start, end]. `pattern_label` is the string label registered with the
    matcher (resolved via `nlp.vocab.strings`).
    '''
    if _matcher_is_empty(matcher):
        raise ValueError(
            'matcher has no registered patterns; add patterns before applying'
        )
    if nlp is None:
        nlp = load_nlp()
    rows = []
    for idx, doc in zip(doc_index, docs):
        for match_id, start, end in matcher(doc):
            label = nlp.vocab.strings[match_id]
            span = doc[start:end]
            rows.append({
                'doc_index': idx,
                'pattern_label': label,
                'span_text': span.text,
                'start': start,
                'end': end,
            })
    return pd.DataFrame(rows, columns=[
        'doc_index', 'pattern_label', 'span_text', 'start', 'end'
    ])


def match_flags(docs, doc_index, matcher, nlp=None, labels=None):
    '''Wide boolean DataFrame: one column per pattern label, indexed by doc_index.

    Joinable back to `treated_df` for per-reporter / per-incident analysis.

    `labels` pins the column set so docs with zero matches still appear as a
    full row of False values. If omitted, columns are derived from observed
    matches in `docs`.
    '''
    long_df = apply_matcher(docs, doc_index, matcher, nlp=nlp)
    observed = sorted(long_df['pattern_label'].unique())
    all_labels = sorted(set(labels) | set(observed)) if labels else observed
    flags = pd.DataFrame(False, index=doc_index, columns=all_labels)
    if long_df.empty:
        return flags
    hits = (long_df.groupby(['doc_index', 'pattern_label']).size()
                   .unstack(fill_value=0) > 0)
    for col in hits.columns:
        if col not in flags.columns:
            flags[col] = False
        flags.loc[hits.index, col] = hits[col].values
    return flags


# ---------------------------------------------------------------------------
# U8 -- displaCy rendering
# ---------------------------------------------------------------------------
def render_displacy_html(docs, doc_index, out_dir, style='ent', sample_n=20,
                         random_state=0, dep_token_warn_threshold=30):
    '''Write per-document displaCy HTML files for a sampled subset of docs.

    Parameters
    ----------
    docs, doc_index :
        Output of `parse_corpus`.
    out_dir : str | Path
        Directory to write HTML files into. Created if missing.
    style : {'ent', 'dep'}
        displaCy render style.
    sample_n : int
        Number of docs to render. Clamped to len(docs).
    random_state : int
        RNG seed for deterministic sampling.

    Returns
    -------
    list[Path] : paths of the written files.
    '''
    try:
        from spacy import displacy
    except ImportError as e:
        raise ImportError('render_displacy_html requires spaCy.') from e

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    n = min(sample_n, len(docs))
    if n <= 0:
        return []
    rng = random.Random(random_state)
    sample_positions = sorted(rng.sample(range(len(docs)), n))

    paths = []
    for pos in sample_positions:
        doc = docs[pos]
        idx = doc_index[pos]
        if style == 'dep' and len(doc) > dep_token_warn_threshold:
            # Just a console warning -- still render, it'll be cramped.
            print(f'warn: doc_index={idx} has {len(doc)} tokens; '
                  f"style='dep' render will be wide.")
        html = displacy.render(doc, style=style, page=True, jupyter=False)
        path = out_dir / f'{style}_{idx}.html'
        path.write_text(html, encoding='utf-8')
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# U9 -- Token + document similarity
# ---------------------------------------------------------------------------
def most_similar_in_corpus(nlp, seed_words, docs, top_k=15, lowercase=True,
                            drop_stop=True):
    '''For each seed word, rank in-corpus lemmas by vector similarity.

    Notes
    -----
    spaCy `token.similarity` uses static word vectors (mean-pooled at the doc
    level). This is *not* contextual similarity -- it's a fixed-vector cosine.
    The EDA value here is in seeing the limitation, not in masking it.
    '''
    # Collect unique non-stop / non-punct lemmas across the corpus.
    lemmas = set()
    for doc in docs:
        for tok in doc:
            if tok.is_punct or tok.is_space:
                continue
            if drop_stop and tok.is_stop:
                continue
            lemma = tok.lemma_.lower() if lowercase else tok.lemma_
            lemmas.add(lemma)

    rows = []
    for seed in seed_words:
        seed_tok = nlp.vocab[seed]
        if not seed_tok.has_vector:
            rows.append({'seed': seed, 'lemma': None, 'similarity': float('nan'),
                         'note': 'seed has no vector'})
            continue
        scored = []
        for lemma in lemmas:
            lex = nlp.vocab[lemma]
            if not lex.has_vector:
                continue
            sim = float(seed_tok.similarity(lex))
            scored.append((lemma, sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        for lemma, sim in scored[:top_k]:
            rows.append({'seed': seed, 'lemma': lemma, 'similarity': sim,
                         'note': ''})
    return pd.DataFrame(rows, columns=['seed', 'lemma', 'similarity', 'note'])


def doc_similarity_matrix(docs, doc_index, sample_n=50, random_state=0):
    '''Pairwise doc.similarity on a deterministic sample.

    Returns a (sample_n, sample_n) symmetric DataFrame indexed by the sampled
    doc_index values.
    '''
    n = min(sample_n, len(docs))
    if n <= 0:
        return pd.DataFrame()
    rng = random.Random(random_state)
    positions = sorted(rng.sample(range(len(docs)), n))
    sampled_docs = [docs[p] for p in positions]
    sampled_idx = [doc_index[p] for p in positions]

    mat = np.zeros((n, n), dtype=float)
    for i in range(n):
        mat[i, i] = 1.0
        for j in range(i + 1, n):
            sim = float(sampled_docs[i].similarity(sampled_docs[j]))
            mat[i, j] = sim
            mat[j, i] = sim
    return pd.DataFrame(mat, index=sampled_idx, columns=sampled_idx)
