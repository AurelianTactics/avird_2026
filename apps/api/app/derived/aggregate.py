"""Live aggregation core (U2) — pure functions over fetched canonical rows.

Reimplements the `eda/eda_utils_co_impact.py` and `eda/eda_utils_sgo.py`
algorithms lean (plain Python, JSON-serializable out) so the deployed `api`
never imports the pandas/matplotlib research stack (plan KTD 2). The functions
here are pure over a list of row dicts; the data layer (`data.fetch_derived_rows`)
owns the parameterized SQL and the canonical clause.

Three views:
- `contact_area_matrix` — SV-area x CP-area co-occurrence (R12); fine grouping,
  the front end sums directions into coarse front/rear/side (plan KTD 7).
- `pre_crash_movement_matrix` — SV-movement x CP-movement co-occurrence (R13).
- `redaction_breakdown` — per-`master_entity` redacted-narrative stats (R14).

`build_heatmaps` bundles the two heatmap matrices; `redaction_breakdown` is
served separately and unfiltered (plan KTD 9). `filter_rows_by_severity` is the
post-fetch severity filter (severity is not a SQL equality — the stored raw
strings normalize to a bucket; plan U2 approach).
"""

from __future__ import annotations

from collections import Counter
from itertools import product
from typing import Any

from ..incidents import _CONTACT_AREAS, _collapse_contact_areas
from ..severity import normalize as normalize_severity

# Redaction markers — reused verbatim from `eda_utils_sgo.REDACTED_PATTERNS`
# so R14 stays aligned with the EDA definition (plan Risks: single edit point).
REDACTED_PATTERNS: tuple[str, ...] = ("redacted", "cbi", "[redacted]", "confidential")

SV_MOVEMENT_COL = "SV Pre-Crash Movement"
CP_MOVEMENT_COL = "CP Pre-Crash Movement"


# --- Matrix shaping ---------------------------------------------------------


def _matrix(
    counter: Counter,
    *,
    sv_axis: list[str],
    cp_axis: list[str],
) -> dict[str, Any]:
    """Shape pair counts into a JSON-serializable matrix the client renders.

    Returns axes (ordered) plus the non-zero cells, so the front end can build
    a grid and re-bucket cells (e.g. coarse contact-area grouping) without a
    second round trip.
    """
    sv_index = {a: i for i, a in enumerate(sv_axis)}
    cp_index = {a: i for i, a in enumerate(cp_axis)}
    cells = [{"sv": sv, "cp": cp, "count": n} for (sv, cp), n in counter.items()]
    cells.sort(key=lambda c: (sv_index[c["sv"]], cp_index[c["cp"]]))
    return {"sv_axis": sv_axis, "cp_axis": cp_axis, "cells": cells}


def _ordered_axis(values: set[str], preferred: list[str]) -> list[str]:
    """Order an axis by a preferred sequence, then any extras alphabetically."""
    in_preferred = [v for v in preferred if v in values]
    extras = sorted(values - set(in_preferred))
    return in_preferred + extras


# --- Contact-area co-occurrence (R12) ---------------------------------------


def contact_area_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-row cartesian (SV area x CP area) pair counts.

    Each row may flag multiple SV and CP contact areas; every (sv, cp) pair
    from a row is counted once (mirrors `eda_utils_co_impact.contact_area_pairs`).
    Rows with no flagged SV *or* no flagged CP area contribute nothing.
    """
    counter: Counter = Counter()
    sv_seen: set[str] = set()
    cp_seen: set[str] = set()
    for row in rows:
        sv = _collapse_contact_areas(row, "SV")
        cp = _collapse_contact_areas(row, "CP")
        if not sv or not cp:
            continue
        sv_seen.update(sv)
        cp_seen.update(cp)
        for s, c in product(sv, cp):
            counter[(s, c)] += 1
    return _matrix(
        counter,
        sv_axis=_ordered_axis(sv_seen, _CONTACT_AREAS),
        cp_axis=_ordered_axis(cp_seen, _CONTACT_AREAS),
    )


# --- Pre-crash movement co-occurrence (R13) ---------------------------------


def _clean_movement(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def pre_crash_movement_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-row (SV movement x CP movement) co-occurrence counts.

    Each row contributes exactly one pair; rows missing either movement are
    skipped. Axes are ordered most-common-first on each side so the grid reads
    top-left = most-common-vs-most-common (mirrors the EDA matrix ordering).
    """
    counter: Counter = Counter()
    sv_totals: Counter = Counter()
    cp_totals: Counter = Counter()
    for row in rows:
        sv = _clean_movement(row.get(SV_MOVEMENT_COL))
        cp = _clean_movement(row.get(CP_MOVEMENT_COL))
        if sv is None or cp is None:
            continue
        counter[(sv, cp)] += 1
        sv_totals[sv] += 1
        cp_totals[cp] += 1

    sv_axis = [m for m, _ in sorted(sv_totals.items(), key=lambda kv: (-kv[1], kv[0]))]
    cp_axis = [m for m, _ in sorted(cp_totals.items(), key=lambda kv: (-kv[1], kv[0]))]
    return _matrix(counter, sv_axis=sv_axis, cp_axis=cp_axis)


# --- Redacted-narrative stats (R14) -----------------------------------------


def _is_redacted(text: Any) -> bool:
    if text is None:
        return False
    value = str(text).strip().lower()
    return any(pattern in value for pattern in REDACTED_PATTERNS)


def redaction_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-`master_entity` redacted-narrative stats: redacted / total / share.

    Mirrors `eda_utils_sgo.redacted_breakdown` over the `Narrative` column, but
    grouped on `master_entity` (the fetched display name), **not** the
    reference default `Reporting Entity` (not fetched). Sorted by redacted desc.
    """
    agg: dict[str, dict[str, int]] = {}
    for row in rows:
        entity = row.get("master_entity")
        rec = agg.setdefault(entity, {"redacted": 0, "total": 0})
        rec["total"] += 1
        if _is_redacted(row.get("Narrative")):
            rec["redacted"] += 1

    out = [
        {
            "entity": entity,
            "redacted": rec["redacted"],
            "total": rec["total"],
            "share": round(rec["redacted"] / rec["total"], 3) if rec["total"] else 0.0,
        }
        for entity, rec in agg.items()
    ]
    out.sort(key=lambda r: r["redacted"], reverse=True)
    return out


# --- Severity post-fetch filter + bundle ------------------------------------


def filter_rows_by_severity(rows: list[dict[str, Any]], bucket: str | None) -> list[dict[str, Any]]:
    """Keep rows whose raw severity normalizes to `bucket` (no-op if `None`).

    Severity is filtered here, post-fetch, rather than via SQL equality: the
    stored `Highest Injury Severity Alleged` holds raw variant strings that map
    to a bucket via `severity.normalize` (plan U2 approach).
    """
    if bucket is None:
        return rows
    return [
        row
        for row in rows
        if normalize_severity(row.get("Highest Injury Severity Alleged")) == bucket
    ]


def build_heatmaps(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Bundle the two heatmap matrices (the shape both routes + agent return)."""
    return {
        "contact_areas": contact_area_matrix(rows),
        "pre_crash": pre_crash_movement_matrix(rows),
    }


__all__ = [
    "REDACTED_PATTERNS",
    "build_heatmaps",
    "contact_area_matrix",
    "filter_rows_by_severity",
    "pre_crash_movement_matrix",
    "redaction_breakdown",
]
