'''
Build / refresh the narrative-embedding cache.

One-shot, idempotent script. Loads the SGO CSVs, dedupes to one canonical
narrative per incident, and embeds them via the HF Inference Providers
serverless API. Re-runs against the same input are free (cache hits).

Run from the repo root::

    python eda/build_narrative_embeddings.py [--model-id ...] [--dataset-id ...]
        [--cache-dir ...] [--batch-size 32] [--limit N] [--dry-run]

The cache file lives under
``<cache-dir>/<model_id_slug>/<dataset-id>.parquet`` and is gitignored by
the repo's ``.gitignore``.
'''
import argparse
import os
import re
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EDA_DIR = REPO_ROOT / 'eda'
DATA_DIR = REPO_ROOT / 'data' / 'nhtsa'
CSV_GLOB = 'SGO-2021-01_Incident_Reports_ADS*.csv'

NARRATIVE_COL = 'Narrative - Same Incident ID'
DEFAULT_MODEL_ID = 'BAAI/bge-base-en-v1.5'
DEFAULT_CACHE_DIR = REPO_ROOT / 'data' / 'embeddings'
DEFAULT_BATCH_SIZE = 32


def _ensure_eda_on_path():
    if str(EDA_DIR) not in sys.path:
        sys.path.insert(0, str(EDA_DIR))


def _discover_csvs():
    paths = sorted(DATA_DIR.glob(CSV_GLOB))
    if not paths:
        raise FileNotFoundError(
            f"No SGO CSVs found under {DATA_DIR} matching {CSV_GLOB}"
        )
    return paths


def _derive_dataset_id(csv_paths):
    '''Pick the latest YYYY_MM_DD seen across input filenames.'''
    dates = []
    for p in csv_paths:
        dates.extend(re.findall(r'(\d{4}_\d{2}_\d{2})', p.name))
    last = max(dates) if dates else 'unknown'
    return f'narratives_dedup_to_{last}'


def _count_cache_rows(cache_path):
    if not cache_path.exists():
        return 0
    import pandas as pd
    return len(pd.read_parquet(cache_path, columns=['text_hash']))


def _format_bytes(n):
    units = ['B', 'KB', 'MB', 'GB']
    f = float(n)
    for u in units:
        if f < 1024 or u == units[-1]:
            return f'{f:.1f} {u}'
        f /= 1024
    return f'{n} B'


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.strip())
    p.add_argument('--model-id', default=DEFAULT_MODEL_ID,
                   help=f'HF model id (default: {DEFAULT_MODEL_ID})')
    p.add_argument('--dataset-id', default=None,
                   help='Cache file stem (default: derived from CSV filenames)')
    p.add_argument('--cache-dir', default=str(DEFAULT_CACHE_DIR),
                   help=f'Cache root (default: {DEFAULT_CACHE_DIR})')
    p.add_argument('--batch-size', type=int, default=DEFAULT_BATCH_SIZE,
                   help=f'Loop batch size (default: {DEFAULT_BATCH_SIZE})')
    p.add_argument('--limit', type=int, default=None,
                   help='If set, embed only the first N dedup'
                        "'d narratives (smoke run).")
    p.add_argument('--dry-run', action='store_true',
                   help='Print what would happen without calling the API.')
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    _ensure_eda_on_path()
    from eda_utils_sgo import load_and_concat_csvs
    from eda_utils_dedupe import dedupe_same_incident
    from eda_utils_embed import embed_texts, _cache_path

    csv_paths = _discover_csvs()
    dataset_id = args.dataset_id or _derive_dataset_id(csv_paths)
    cache_dir = Path(args.cache_dir)

    if cache_dir.exists() and not cache_dir.is_dir():
        raise NotADirectoryError(
            f'--cache-dir points at a file, not a directory: {cache_dir}'
        )

    cache_path = _cache_path(cache_dir, args.model_id, dataset_id)

    print('=' * 60)
    print('build_narrative_embeddings')
    print('=' * 60)
    print(f'  CSVs:        {len(csv_paths)} found under {DATA_DIR}')
    for p in csv_paths:
        print(f'    - {p.name}')
    print(f'  model_id:    {args.model_id}')
    print(f'  dataset_id:  {dataset_id}')
    print(f'  cache_path:  {cache_path}')
    if args.limit is not None:
        print(f'  limit:       {args.limit} (smoke run)')

    df = load_and_concat_csvs([str(p) for p in csv_paths])
    df_clean = dedupe_same_incident(df, verbose=False)
    narratives = df_clean[NARRATIVE_COL]

    if args.limit is not None:
        narratives = narratives.head(args.limit)

    n_input = len(narratives)
    n_nonempty = int(narratives.dropna().astype(str).map(str.strip).str.len().gt(0).sum())
    rows_in_cache_before = _count_cache_rows(cache_path)

    print(f'  input rows:  {n_input} (non-empty after strip: {n_nonempty})')
    print(f'  cache rows before run: {rows_in_cache_before}')

    if args.dry_run:
        print('  --dry-run: skipping API call. Exit 0.')
        return 0

    t0 = time.perf_counter()
    emb, idx = embed_texts(
        narratives,
        model_id=args.model_id,
        cache_dir=str(cache_dir),
        dataset_id=dataset_id,
        batch_size=args.batch_size,
    )
    elapsed = time.perf_counter() - t0

    rows_in_cache_after = _count_cache_rows(cache_path)
    rows_added = rows_in_cache_after - rows_in_cache_before
    cache_size = cache_path.stat().st_size if cache_path.exists() else 0

    print('-' * 60)
    print(f'  embeddings shape: {emb.shape}')
    print(f'  rows added (API calls): {rows_added}')
    print(f'  rows cache-hit:         {n_nonempty - rows_added}')
    print(f'  total cache rows now:   {rows_in_cache_after}')
    print(f'  cache file size:        {_format_bytes(cache_size)}')
    print(f'  elapsed:                {elapsed:.2f}s')
    print('=' * 60)
    return 0


if __name__ == '__main__':
    sys.exit(main())
