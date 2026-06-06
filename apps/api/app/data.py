"""Data-access seam over `treated_incident_reports`.

Routes depend on `IncidentData` via FastAPI `Depends(get_incident_data)`
instead of touching asyncpg directly, so route tests override the
dependency with a fake and run without a live Postgres — exactly how
`tests/test_health.py` overrides `check_db`.

Two data sides live here, and the split is deliberate:

- The **list** (`fetch_incidents` / `count_incidents`) shows *raw* report
  rows with **no canonical dedup** — every report appears, including
  multiple reports of one incident.
- The **groupings** aggregate (`fetch_entity_severity_counts`) is *treated*
  and applies `CANONICAL_CLAUSE`.

`CANONICAL_CLAUSE` is defined once here and used **only** by the groupings
query — the list query must never apply it (see plan KTD 2).
"""

from __future__ import annotations

from typing import Any

from .db import get_pool

TABLE = "treated_incident_reports"

# Canonical-row filter — TREATED groupings only (U4). The raw list (U3) omits it.
# `is_latest_of_multiple_report` is a cleaned snake_case column (no quoting needed).
CANONICAL_CLAUSE = "is_latest_of_multiple_report = true"

# Sort allow-list: public sort key -> fixed, double-quoted raw column identifier.
# This map is the SQL identifier-injection control (plan KTD 4) — the resolved
# value is always one of these constants, never an interpolated request param.
SORT_COLUMNS: dict[str, str] = {
    "date": '"Incident Date"',
    "entity": '"Reporting Entity"',
    "severity": '"Highest Injury Severity Alleged"',
}

# Raw column subset rendered by the list (U7). Quoted because they are
# mixed-case-with-spaces raw passthrough columns.
LIST_COLUMNS: list[str] = [
    '"Report ID"',
    '"Reporting Entity"',
    '"Incident Date"',
    '"City"',
    '"State"',
    '"Highest Injury Severity Alleged"',
    '"Crash With"',
]

PAGE_SIZE = 50


class IncidentData:
    """Live asyncpg-backed implementation of the data-access surface.

    Route tests do not use this class — they override `get_incident_data`
    with an in-memory fake. It is exercised end-to-end only against the
    deployed DB.
    """

    async def fetch_incidents(
        self, *, limit: int, offset: int, order_column: str, direction: str
    ) -> list[dict[str, Any]]:
        # `order_column` and `direction` come only from fixed allow-lists in
        # the route (SORT_COLUMNS + {"ASC","DESC"}) — never raw request params.
        query = (
            f"SELECT {', '.join(LIST_COLUMNS)} FROM {TABLE} "
            f"ORDER BY {order_column} {direction} "
            "LIMIT $1 OFFSET $2"
        )
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(query, limit, offset)
        return [dict(r) for r in rows]

    async def count_incidents(self) -> int:
        # Unfiltered COUNT(*) — the list is not deduped (plan KTD 2).
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            value = await conn.fetchval(f"SELECT COUNT(*) FROM {TABLE}")
        return int(value or 0)

    async def fetch_incident(self, report_id: str) -> dict[str, Any] | None:
        # No canonical filter — detail looks up the exact reported row.
        query = f'SELECT * FROM {TABLE} WHERE "Report ID" = $1 LIMIT 1'
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            row = await conn.fetchrow(query, report_id)
        return dict(row) if row is not None else None

    async def fetch_entity_severity_counts(self) -> list[dict[str, Any]]:
        # TREATED: canonical rows only. Returns (master_entity, raw_severity, n)
        # tuples; the route pivots into the bucket matrix via severity.normalize().
        query = (
            "SELECT master_entity, "
            '"Highest Injury Severity Alleged" AS raw_severity, '
            "COUNT(*) AS n "
            f"FROM {TABLE} "
            f"WHERE {CANONICAL_CLAUSE} "
            "GROUP BY master_entity, "
            '"Highest Injury Severity Alleged"'
        )
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(query)
        return [dict(r) for r in rows]


def get_incident_data() -> IncidentData:
    """FastAPI dependency. Tests override this with an in-memory fake."""
    return IncidentData()
