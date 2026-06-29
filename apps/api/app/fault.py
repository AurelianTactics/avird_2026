"""Read-only fault-verdict route (Feature 1 read path, covers R4).

Surfaces the precomputed `fault_analysis` verdict for one report. **No LLM
deps on this path** — the verdict is computed offline by `fault/judge_batch.py`
and only read back here, so the `api` runtime stays key-free for the judge.

A report can carry verdicts under multiple `fault_version`s (a re-run with a
newer model/prompt appends a new version); this route returns the **most
recent** one. A report with no verdict at all returns 404 — the `web` page maps
that to a graceful "no verdict yet" empty state, never a crash.

Data access goes through `FaultData`/`get_fault_data` so route tests override
the dependency with an in-memory fake (mirrors `incidents.get_incident_data`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .db import get_pool

router = APIRouter()

TABLE = "fault_analysis"


class FaultData:
    """Live asyncpg-backed accessor over `fault_analysis`. Tests use a fake."""

    async def fetch_fault(self, report_id: str) -> dict[str, Any] | None:
        # Most-recent verdict wins when several fault_versions exist. created_at
        # is an ISO-8601 TEXT timestamp, so DESC orders it lexicographically.
        query = (
            "SELECT report_id, fault_version, is_av_at_fault, "
            "av_fault_percentage, short_explanation_of_decision, model, "
            "created_at "
            f"FROM {TABLE} WHERE report_id = $1 "
            "ORDER BY created_at DESC LIMIT 1"
        )
        pool = await get_pool()
        async with pool.acquire(timeout=5) as conn:
            row = await conn.fetchrow(query, report_id)
        return dict(row) if row is not None else None


def get_fault_data() -> FaultData:
    """FastAPI dependency. Tests override this with an in-memory fake."""
    return FaultData()


def _shape_fault(row: dict[str, Any]) -> dict[str, Any]:
    # av_fault_percentage comes back as Decimal from NUMERIC — coerce to float
    # for JSON. A parse-failure sentinel row carries NULL verdict + NULL pct +
    # an error string; those NULLs pass straight through.
    pct = row.get("av_fault_percentage")
    fault = row.get("is_av_at_fault")
    return {
        "report_id": row.get("report_id"),
        "fault_version": row.get("fault_version"),
        "is_av_at_fault": None if fault is None else bool(fault),
        "av_fault_percentage": None if pct is None else float(pct),
        "short_explanation": row.get("short_explanation_of_decision"),
        "model": row.get("model"),
        "created_at": row.get("created_at"),
    }


@router.get("/incidents/{report_id}/fault")
async def get_fault(
    report_id: str,
    data: FaultData = Depends(get_fault_data),
) -> dict[str, Any]:
    row = await data.fetch_fault(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="no fault verdict for this report")
    return _shape_fault(row)
