"""Raw incident routes: paginated list + per-incident one-pager.

Both routes are RAW (plan KTD 1): they surface raw SGO column values with
**no canonical dedup** (plan KTD 2). Read-only — no write/mutation routes.

Sort is resolved through `data.SORT_COLUMNS` + a fixed direction map; the raw
request params never reach `ORDER BY` directly (plan KTD 4).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .data import PAGE_SIZE, SORT_COLUMNS, IncidentData, get_incident_data

router = APIRouter()

_DIRECTIONS: dict[str, str] = {"asc": "ASC", "desc": "DESC"}
_DEFAULT_SORT = "date"
_DEFAULT_DIR = "desc"

# Contact-area direction suffixes (the `* Contact Area - <dir>` raw columns).
_CONTACT_AREAS: list[str] = [
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

# Values that read as "not set" for a checkbox-style raw column.
_FALSEY = {"", "no", "false", "0", "n", "none"}


def _truthy(value: Any) -> bool:
    return value is not None and str(value).strip().lower() not in _FALSEY


def _collapse_contact_areas(row: dict[str, Any], prefix: str) -> list[str]:
    return [area for area in _CONTACT_AREAS if _truthy(row.get(f"{prefix} Contact Area - {area}"))]


def _shape_list_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": row.get("Report ID"),
        "reporting_entity": row.get("Reporting Entity"),
        "incident_date": row.get("Incident Date"),
        "city": row.get("City"),
        "state": row.get("State"),
        # RAW severity string — not a normalized bucket (plan KTD 5).
        "severity": row.get("Highest Injury Severity Alleged"),
        "crash_with": row.get("Crash With"),
    }


def _shape_other_report(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": row.get("Report ID"),
        "reporting_entity": row.get("Reporting Entity"),
    }


def _shape_detail(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": row.get("Report ID"),
        "reporting_entity": row.get("Reporting Entity"),
        "operating_entity": row.get("Operating Entity"),
        "incident_date": row.get("Incident Date"),
        "incident_time": row.get("Incident Time"),
        "city": row.get("City"),
        "state": row.get("State"),
        "roadway_type": row.get("Roadway Type"),
        "roadway_description": row.get("Roadway Description"),
        "crash_with": row.get("Crash With"),
        "severity": row.get("Highest Injury Severity Alleged"),
        "property_damage": row.get("Property Damage?"),
        "cp_pre_crash_movement": row.get("CP Pre-Crash Movement"),
        "sv_pre_crash_movement": row.get("SV Pre-Crash Movement"),
        "cp_airbags_deployed": row.get("CP Any Air Bags Deployed?"),
        "sv_airbags_deployed": row.get("SV Any Air Bags Deployed?"),
        "cp_vehicle_towed": row.get("CP Was Vehicle Towed?"),
        "sv_vehicle_towed": row.get("SV Was Vehicle Towed?"),
        "passengers_belted": row.get("SV Were All Passengers Belted?"),
        "precrash_speed": row.get("SV Precrash Speed (MPH)"),
        "law_enforcement_investigating": row.get("Law Enforcement Investigating?"),
        "cp_contact_areas": _collapse_contact_areas(row, "CP"),
        "sv_contact_areas": _collapse_contact_areas(row, "SV"),
        "narrative": row.get("Narrative"),
    }


@router.get("/incidents")
async def list_incidents(
    page: int = 1,
    sort: str = _DEFAULT_SORT,
    dir: str = _DEFAULT_DIR,
    data: IncidentData = Depends(get_incident_data),
) -> dict[str, Any]:
    # Allow-list resolution — out-of-set values fall back to the default
    # (the injection control; the raw param is never interpolated).
    order_column = SORT_COLUMNS.get(sort, SORT_COLUMNS[_DEFAULT_SORT])
    direction = _DIRECTIONS.get(dir, _DIRECTIONS[_DEFAULT_DIR])
    page = page if page >= 1 else 1
    offset = (page - 1) * PAGE_SIZE

    rows = await data.fetch_incidents(
        limit=PAGE_SIZE, offset=offset, order_column=order_column, direction=direction
    )
    total = await data.count_incidents()  # unfiltered — the list is not deduped.
    return {
        "items": [_shape_list_row(r) for r in rows],
        "page": page,
        "page_size": PAGE_SIZE,
        "total": total,
    }


@router.get("/incidents/{report_id}")
async def get_incident(
    report_id: str,
    data: IncidentData = Depends(get_incident_data),
) -> dict[str, Any]:
    row = await data.fetch_incident(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="incident not found")

    # Other reports of the same incident, linked via the raw
    # "Same Incident ID" column (blank for ~0.5% of rows -> no lookup).
    same_incident_id = str(row.get("Same Incident ID") or "").strip()
    others: list[dict[str, Any]] = []
    if same_incident_id:
        others = await data.fetch_other_reports(same_incident_id, report_id)

    detail = _shape_detail(row)
    detail["other_reports"] = [_shape_other_report(o) for o in others]
    return detail
