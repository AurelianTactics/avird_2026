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

from typing import TYPE_CHECKING, Any

from .db import get_pool

if TYPE_CHECKING:
    from .derived.filters import DerivedFilter

TABLE = "treated_incident_reports"

# Canonical-row filter — TREATED groupings only (U4). The raw list (U3) omits it.
# `is_latest_of_multiple_report` is a cleaned snake_case column (no quoting needed).
CANONICAL_CLAUSE = "is_latest_of_multiple_report = true"

# Sort allow-list: public sort key -> fixed column identifier. This map is
# the SQL identifier-injection control (plan KTD 4) — the resolved value is
# always one of these constants, never an interpolated request param.
# "date" sorts the typed DATE column, not the raw '"Incident Date"' text —
# raw values like 'MAR-2026' sort alphabetically ('SEP-2025' lands above
# 'MAR-2026'), which is the bug the promoted column exists to avoid.
SORT_COLUMNS: dict[str, str] = {
    "date": "incident_date",
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

# Contact-area direction suffixes for the derived heatmap fetch. Mirrors
# `incidents._CONTACT_AREAS` (the same `* Contact Area - <dir>` raw columns
# `incidents._collapse_contact_areas` reads); kept here to avoid importing
# `incidents` (which imports this module) and the resulting cycle.
_DERIVED_CONTACT_AREAS: list[str] = [
    "Rear Left",
    "Left",
    "Front Left",
    "Rear",
    "Top",
    "Front",
    "Rear Right",
    "Right",
    "Front Right",
    "Bottom",
]

# Columns the three derived views need (plan U2). Quoted mixed-case raw
# passthrough columns; `master_entity` is the cleaned snake_case column.
DERIVED_COLUMNS: list[str] = [
    *[f'"SV Contact Area - {a}"' for a in _DERIVED_CONTACT_AREAS],
    *[f'"CP Contact Area - {a}"' for a in _DERIVED_CONTACT_AREAS],
    '"SV Pre-Crash Movement"',
    '"CP Pre-Crash Movement"',
    "master_entity",
    '"State Clean"',
    '"Highest Injury Severity Alleged"',
    '"Narrative"',
]


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
        # NULLS LAST so unparsed dates never crowd the top of a desc sort;
        # "Report ID" tiebreak keeps pagination stable across pages.
        query = (
            f"SELECT {', '.join(LIST_COLUMNS)} FROM {TABLE} "
            f'ORDER BY {order_column} {direction} NULLS LAST, "Report ID" ASC '
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

    async def fetch_other_reports(
        self, same_incident_id: str, report_id: str
    ) -> list[dict[str, Any]]:
        # Other reports of the SAME incident (shared "Same Incident ID"),
        # excluding the report being viewed. DISTINCT because resubmissions
        # repeat a Report ID across versions.
        query = (
            'SELECT DISTINCT "Report ID", "Reporting Entity" '
            f"FROM {TABLE} "
            'WHERE "Same Incident ID" = $1 AND "Report ID" <> $2 '
            'ORDER BY "Report ID"'
        )
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(query, same_incident_id, report_id)
        return [dict(r) for r in rows]

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

    async def fetch_known_values(self) -> dict[str, list[str]]:
        # Allow-list vocabulary for the NL filter (plan U1/U2): the distinct,
        # canonical-scoped `master_entity` and `State Clean` sets. Sourced here
        # so the resolver never trusts caller-supplied known values. Cheap at
        # current data size; queried per request (no premature cache, R22).
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            entities = await conn.fetch(
                f"SELECT DISTINCT master_entity FROM {TABLE} "
                f"WHERE {CANONICAL_CLAUSE} AND master_entity IS NOT NULL"
            )
            states = await conn.fetch(
                f'SELECT DISTINCT "State Clean" FROM {TABLE} '
                f'WHERE {CANONICAL_CLAUSE} AND "State Clean" IS NOT NULL'
            )
        return {
            "entities": sorted(r["master_entity"] for r in entities),
            "states": sorted(r["State Clean"] for r in states),
        }

    async def fetch_derived_rows(self, filt: DerivedFilter) -> list[dict[str, Any]]:
        # Canonical rows only (plan KTD 8). Entity and state are applied as
        # parameterized equality on FIXED identifiers (`master_entity`,
        # `"State Clean"`) with `$n` values only — the resolved values come from
        # the U1 allow-list, never raw input (plan KTD 3). Severity is NOT a SQL
        # clause: the raw severity strings normalize to a bucket, so the caller
        # applies `aggregate.filter_rows_by_severity` post-fetch.
        clauses = [CANONICAL_CLAUSE]
        params: list[Any] = []
        if filt.entity is not None:
            params.append(filt.entity)
            clauses.append(f"master_entity = ${len(params)}")
        if filt.state is not None:
            params.append(filt.state)
            clauses.append(f'"State Clean" = ${len(params)}')
        query = f"SELECT {', '.join(DERIVED_COLUMNS)} FROM {TABLE} WHERE {' AND '.join(clauses)}"
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            rows = await conn.fetch(query, *params)
        return [dict(r) for r in rows]


def get_incident_data() -> IncidentData:
    """FastAPI dependency. Tests override this with an in-memory fake."""
    return IncidentData()
