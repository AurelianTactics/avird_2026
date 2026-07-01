"""Ingest deduped narratives + cached vectors into the RAG store (plan P2, U8).

**The ingest is the real work, not "load the parquet".** The embedding cache
(``eda/eda_utils_embed.py``) stores only ``{text_hash, vector, dim}`` — it has no
incident id and no narrative text, and returns a positional ``doc_index``, not a
``Same Incident ID``. So two of the three target columns can't come from the
cache. This module:

1. Re-derives the canonical ``(Same Incident ID, Narrative - Same Incident ID)``
   rows the way ``eda/build_narrative_embeddings.py`` does — ``load_and_concat_csvs``
   → ``dedupe_same_incident`` — which needs the raw NHTSA CSVs under ``data/nhtsa/``.
2. Re-hashes each narrative with the *same* ``_text_hash`` the cache was written
   with, and joins to the cache vector by that hash.
3. Carries the incident id + narrative from the deduped frame and the vector from
   the cache into ``(incident_id, narrative, vector)`` rows.

A narrative whose re-hash finds no cache vector is **reported** (count + sample),
never silently dropped — that's the hash-join contract.

This is an **offline build step** (like ``build_narrative_embeddings.py``), run
from the shared dev env; the heavy imports (pandas, the flat ``eda`` modules,
pyarrow) are lazy so importing this module costs nothing and the api never loads
them at runtime.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
EDA_DIR = REPO_ROOT / "eda"
DATA_DIR = REPO_ROOT / "data" / "nhtsa"
CSV_GLOB = "SGO-2021-01_Incident_Reports_ADS*.csv"

NARRATIVE_COL = "Narrative - Same Incident ID"
SID_COL = "Same Incident ID"
DEFAULT_MODEL_ID = "BAAI/bge-base-en-v1.5"
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "embeddings"
TABLE = "narrative_embeddings"


def _text_hash(text: str) -> str:
    """sha256 of the stripped text — must match ``eda_utils_embed._text_hash``."""
    return hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()


# --- the pure hash-join (testable without pandas/pyarrow) -------------------


def join_vectors(rows: list[dict[str, Any]], cache: dict[str, Any]) -> tuple[list[dict], dict]:
    """Join deduped rows to cache vectors by narrative hash.

    ``rows`` is ``[{incident_id, narrative}, ...]``; ``cache`` is
    ``{text_hash: vector}``. Returns ``(matched, report)`` where ``matched`` rows
    carry ``(incident_id, narrative, vector)`` and ``report`` accounts for every
    input row — empties skipped, misses sampled — so nothing vanishes silently.
    """
    matched: list[dict] = []
    unmatched: list[str] = []
    n_empty = 0
    for row in rows:
        narrative = str(row.get("narrative") or "").strip()
        incident_id = str(row.get("incident_id") or "").strip()
        if not narrative:
            n_empty += 1
            continue
        vector = cache.get(_text_hash(narrative))
        if vector is None:
            unmatched.append(incident_id or "(no id)")
            continue
        matched.append(
            {"incident_id": incident_id or "(no id)", "narrative": narrative, "vector": vector}
        )
    report = {
        "n_rows": len(rows),
        "n_matched": len(matched),
        "n_unmatched": len(unmatched),
        "n_empty": n_empty,
        "unmatched_sample": unmatched[:5],
    }
    return matched, report


# --- offline derivation (lazy pandas / eda / pyarrow) -----------------------


def derive_canonical_rows(*, limit: int | None = None) -> list[dict[str, Any]]:
    """Re-derive ``[{incident_id, narrative}]`` from the raw CSVs via the eda
    dedup pipeline (lazy import; needs ``data/nhtsa/`` present)."""
    if str(EDA_DIR) not in sys.path:
        sys.path.insert(0, str(EDA_DIR))
    from eda_utils_dedupe import dedupe_same_incident  # noqa: E402
    from eda_utils_sgo import load_and_concat_csvs  # noqa: E402

    csv_paths = sorted(DATA_DIR.glob(CSV_GLOB))
    if not csv_paths:
        raise FileNotFoundError(f"no SGO CSVs under {DATA_DIR} matching {CSV_GLOB}")
    df = load_and_concat_csvs([str(p) for p in csv_paths])
    deduped = dedupe_same_incident(df, verbose=False)
    rows: list[dict[str, Any]] = []
    for i, (_, r) in enumerate(deduped.iterrows()):
        if limit is not None and i >= limit:
            break
        sid = r.get(SID_COL)
        # A missing Same Incident ID arrives as pandas NaN, which str()s to
        # "nan" — never let that leak into provenance the UI shows.
        sid_str = "" if sid is None else str(sid).strip()
        if sid_str.lower() in ("", "nan", "none"):
            sid_str = f"row-{i}"
        rows.append({"incident_id": sid_str, "narrative": r.get(NARRATIVE_COL)})
    return rows


def load_cache(
    *, cache_dir: Path = DEFAULT_CACHE_DIR, model_id: str = DEFAULT_MODEL_ID, dataset_id: str
) -> dict[str, Any]:
    """Load ``{text_hash: vector}`` from the parquet cache (lazy pandas/pyarrow)."""
    import numpy as np
    import pandas as pd

    slug = model_id.replace("/", "__")
    path = Path(cache_dir) / slug / f"{dataset_id}.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"embedding cache not found at {path}. Build it first with "
            "`python eda/build_narrative_embeddings.py` (needs HF_TOKEN)."
        )
    df = pd.read_parquet(path)
    return {
        row["text_hash"]: np.asarray(row["vector"], dtype=np.float32) for _, row in df.iterrows()
    }


def build_corpus_with_vectors(*, dataset_id: str, limit: int | None = None):
    """Derive rows, load cache, join → ``(ids, narratives, matrix, report)`` for
    the in-memory store."""
    import numpy as np

    rows = derive_canonical_rows(limit=limit)
    cache = load_cache(dataset_id=dataset_id)
    matched, report = join_vectors(rows, cache)
    ids = [m["incident_id"] for m in matched]
    narratives = [m["narrative"] for m in matched]
    matrix = (
        np.vstack([m["vector"] for m in matched]) if matched else np.zeros((0, 0), dtype=np.float32)
    )
    return ids, narratives, matrix, report


async def ingest_pgvector(conn, matched: list[dict]) -> int:
    """Upsert matched rows into ``narrative_embeddings``. Returns the row count."""
    for m in matched:
        vec = "[" + ",".join(repr(float(x)) for x in m["vector"]) + "]"
        await conn.execute(
            f"INSERT INTO {TABLE} (incident_id, narrative, embedding) "
            f"VALUES ($1, $2, $3::vector) "
            f"ON CONFLICT (incident_id) DO UPDATE SET "
            f"narrative = EXCLUDED.narrative, embedding = EXCLUDED.embedding",
            m["incident_id"],
            m["narrative"],
            vec,
        )
    return len(matched)


__all__ = [
    "build_corpus_with_vectors",
    "derive_canonical_rows",
    "ingest_pgvector",
    "join_vectors",
    "load_cache",
]
