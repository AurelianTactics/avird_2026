"""Tests for the live aggregation core + derived data-layer fetch (U2).

Pure aggregation functions are tested directly over row dicts (no DB). The
data-layer SQL is tested via a fake pool asserting the canonical clause and the
parameterized entity/state equality.
"""

from __future__ import annotations

from app import data as data_module
from app.data import DERIVED_COLUMNS, IncidentData
from app.derived.aggregate import (
    build_heatmaps,
    contact_area_matrix,
    filter_rows_by_severity,
    pre_crash_movement_matrix,
    redaction_breakdown,
)
from app.derived.filters import DerivedFilter


def _contact_row(sv=(), cp=(), **extra):
    row = dict(extra)
    for area in sv:
        row[f"SV Contact Area - {area}"] = "Y"
    for area in cp:
        row[f"CP Contact Area - {area}"] = "Y"
    return row


def _cell(matrix, sv, cp):
    for c in matrix["cells"]:
        if c["sv"] == sv and c["cp"] == cp:
            return c["count"]
    return 0


# --- Contact-area matrix ----------------------------------------------------


def test_contact_area_single_pair():
    rows = [_contact_row(sv=["Front"], cp=["Rear"])]
    mat = contact_area_matrix(rows)
    assert _cell(mat, "Front", "Rear") == 1
    assert mat["sv_axis"] == ["Front"]
    assert mat["cp_axis"] == ["Rear"]


def test_contact_area_multiple_flags_make_multiple_pairs():
    # 2 SV areas x 2 CP areas = 4 cartesian pairs from one row.
    rows = [_contact_row(sv=["Front", "Left"], cp=["Rear", "Right"])]
    mat = contact_area_matrix(rows)
    assert _cell(mat, "Front", "Rear") == 1
    assert _cell(mat, "Front", "Right") == 1
    assert _cell(mat, "Left", "Rear") == 1
    assert _cell(mat, "Left", "Right") == 1
    assert sum(c["count"] for c in mat["cells"]) == 4


def test_contact_area_axis_follows_canonical_order():
    rows = [_contact_row(sv=["Front", "Rear"], cp=["Front"])]
    mat = contact_area_matrix(rows)
    # Canonical order puts Rear before Front.
    assert mat["sv_axis"] == ["Rear", "Front"]


def test_contact_area_row_missing_one_side_excluded():
    rows = [
        _contact_row(sv=["Front"], cp=[]),  # no CP -> no pair
        _contact_row(sv=[], cp=["Rear"]),  # no SV -> no pair
    ]
    mat = contact_area_matrix(rows)
    assert mat["cells"] == []


# --- Pre-crash movement matrix ----------------------------------------------


def _move_row(sv, cp, **extra):
    return {
        "SV Pre-Crash Movement": sv,
        "CP Pre-Crash Movement": cp,
        **extra,
    }


def test_pre_crash_co_occurrence_counts():
    rows = [
        _move_row("Going Straight", "Stopped"),
        _move_row("Going Straight", "Stopped"),
        _move_row("Turning Left", "Going Straight"),
    ]
    mat = pre_crash_movement_matrix(rows)
    assert _cell(mat, "Going Straight", "Stopped") == 2
    assert _cell(mat, "Turning Left", "Going Straight") == 1


def test_pre_crash_blank_movement_excluded():
    rows = [
        _move_row("Going Straight", None),
        _move_row("", "Stopped"),
        _move_row("  ", "Stopped"),
    ]
    assert pre_crash_movement_matrix(rows)["cells"] == []


def test_pre_crash_axis_ordered_most_common_first():
    rows = [
        _move_row("Rare", "X"),
        _move_row("Common", "X"),
        _move_row("Common", "X"),
    ]
    mat = pre_crash_movement_matrix(rows)
    assert mat["sv_axis"][0] == "Common"


# --- Redaction breakdown ----------------------------------------------------


def test_redaction_breakdown_counts_markers_per_entity():
    rows = [
        {"master_entity": "Waymo", "Narrative": "vehicle was [REDACTED] at speed"},
        {"master_entity": "Waymo", "Narrative": "see CBI attachment"},
        {"master_entity": "Waymo", "Narrative": "a clean narrative"},
        {"master_entity": "Cruise", "Narrative": "confidential business information"},
    ]
    out = {r["entity"]: r for r in redaction_breakdown(rows)}
    assert out["Waymo"]["redacted"] == 2
    assert out["Waymo"]["total"] == 3
    assert out["Waymo"]["share"] == round(2 / 3, 3)
    assert out["Cruise"]["redacted"] == 1
    assert out["Cruise"]["total"] == 1
    assert out["Cruise"]["share"] == 1.0


def test_redaction_clean_entity_zero_share():
    rows = [{"master_entity": "Zoox", "Narrative": "ordinary text"}]
    out = redaction_breakdown(rows)
    assert out[0]["redacted"] == 0
    assert out[0]["share"] == 0.0


def test_redaction_sorted_by_redacted_desc():
    rows = [
        {"master_entity": "Low", "Narrative": "clean"},
        {"master_entity": "High", "Narrative": "redacted"},
        {"master_entity": "High", "Narrative": "redacted"},
    ]
    assert [r["entity"] for r in redaction_breakdown(rows)] == ["High", "Low"]


# --- Severity post-fetch filter ---------------------------------------------


def test_filter_rows_by_severity_keeps_matching_bucket():
    rows = [
        {"Highest Injury Severity Alleged": "Fatality"},
        {"Highest Injury Severity Alleged": "Minor"},
        {"Highest Injury Severity Alleged": "No Apparent Injury"},
    ]
    kept = filter_rows_by_severity(rows, "Fatality")
    assert kept == [{"Highest Injury Severity Alleged": "Fatality"}]


def test_filter_rows_by_severity_none_is_noop():
    rows = [{"Highest Injury Severity Alleged": "Minor"}]
    assert filter_rows_by_severity(rows, None) is rows


# --- build_heatmaps + empty set ---------------------------------------------


def test_build_heatmaps_bundles_both_matrices():
    rows = [_contact_row(sv=["Front"], cp=["Rear"], **_move_row("A", "B"))]
    out = build_heatmaps(rows)
    assert set(out) == {"contact_areas", "pre_crash"}
    assert _cell(out["contact_areas"], "Front", "Rear") == 1
    assert _cell(out["pre_crash"], "A", "B") == 1


def test_empty_rows_yield_empty_matrices_no_error():
    out = build_heatmaps([])
    assert out["contact_areas"]["cells"] == []
    assert out["pre_crash"]["cells"] == []


# --- Data-layer SQL tests (fake pool) ---------------------------------------


class _FakeConn:
    def __init__(self, fetch_result):
        self._fetch_result = fetch_result
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        return self._fetch_result


class _FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self, timeout=None):
        return _FakeAcquire(self.conn)


def _patch_pool(monkeypatch, conn):
    async def _get_pool():
        return _FakePool(conn)

    monkeypatch.setattr(data_module, "get_pool", _get_pool)


async def test_fetch_derived_rows_applies_canonical_clause(monkeypatch):
    conn = _FakeConn(fetch_result=[])
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_derived_rows(DerivedFilter())
    query, args = conn.queries[0]
    assert data_module.CANONICAL_CLAUSE in query
    assert args == ()


async def test_fetch_derived_rows_parameterizes_entity_and_state(monkeypatch):
    conn = _FakeConn(fetch_result=[])
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_derived_rows(DerivedFilter(entity="Waymo", state="AZ"))
    query, args = conn.queries[0]
    assert "master_entity = $1" in query
    assert '"State Clean" = $2' in query
    assert args == ("Waymo", "AZ")
    # The raw value is never interpolated into the SQL text.
    assert "Waymo" not in query


async def test_fetch_derived_rows_selects_all_derived_columns(monkeypatch):
    conn = _FakeConn(fetch_result=[])
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_derived_rows(DerivedFilter())
    query, _ = conn.queries[0]
    for col in DERIVED_COLUMNS:
        assert col in query


async def test_fetch_known_values_distinct_canonical_scoped(monkeypatch):
    conn = _FakeConn(fetch_result=[{"master_entity": "Waymo", "State Clean": "AZ"}])
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_known_values()
    # Two DISTINCT queries, both canonical-scoped.
    assert len(conn.queries) == 2
    for query, _ in conn.queries:
        assert "DISTINCT" in query
        assert data_module.CANONICAL_CLAUSE in query
