"""Treated entity x severity groupings route (U4, covers R5).

TREATED side (plan KTD 1): aggregates **canonical** rows only — the data
layer applies `CANONICAL_CLAUSE`. Bucket logic lives in `severity.normalize()`
(plan KTD 5); this route fetches `(master_entity, raw_severity, n)` and pivots
in Python so SQL stays simple and the bucket map has a single home.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .data import IncidentData, get_incident_data
from .severity import BUCKET_ORDER, normalize

router = APIRouter()


@router.get("/groupings/entity-severity")
async def entity_severity(
    data: IncidentData = Depends(get_incident_data),
) -> dict[str, Any]:
    counts = await data.fetch_entity_severity_counts()

    # entity -> {bucket: n}, zero-filled across all seven buckets.
    matrix: dict[str, dict[str, int]] = {}
    for row in counts:
        entity = row.get("master_entity")
        bucket = normalize(row.get("raw_severity"))
        n = int(row.get("n") or 0)
        buckets = matrix.setdefault(entity, {b: 0 for b in BUCKET_ORDER})
        buckets[bucket] += n

    rows = [
        {"entity": entity, "counts": buckets, "total": sum(buckets.values())}
        for entity, buckets in matrix.items()
    ]
    # Heaviest entities first (confirmed orderable at build time).
    rows.sort(key=lambda r: r["total"], reverse=True)

    return {"buckets": BUCKET_ORDER, "rows": rows}
