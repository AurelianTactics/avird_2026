"""Tests for the raw incident routes (U3, covers R1/R2/R3).

Two layers:
  - Route tests override `get_incident_data` with an in-memory fake — they
    prove sort allow-listing, pagination math, response shape, and 404s
    without a live DB (mirrors `tests/test_health.py`'s `check_db` override).
  - Data-layer SQL tests drive the real `IncidentData` against a fake pool to
    prove the list query applies **no** canonical clause and offsets correctly
    (guards the KTD-2 deviation).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import data as data_module
from app.data import IncidentData
from app.incidents import get_incident_data
from app.main import app

# --- Route tests via dependency override -----------------------------------


class FakeData:
    def __init__(self, *, items=None, total=0, detail=None, others=None):
        self.items = items if items is not None else []
        self.total = total
        self.detail = detail
        self.others = others if others is not None else []
        self.calls: dict[str, object] = {}

    async def fetch_incidents(self, *, limit, offset, order_column, direction):
        self.calls["fetch_incidents"] = {
            "limit": limit,
            "offset": offset,
            "order_column": order_column,
            "direction": direction,
        }
        return self.items

    async def count_incidents(self):
        self.calls["count_incidents"] = True
        return self.total

    async def fetch_incident(self, report_id):
        self.calls["fetch_incident"] = report_id
        return self.detail

    async def fetch_other_reports(self, same_incident_id, report_id):
        self.calls["fetch_other_reports"] = {
            "same_incident_id": same_incident_id,
            "report_id": report_id,
        }
        return self.others


def _use(fake: FakeData):
    app.dependency_overrides[get_incident_data] = lambda: fake


def _clear():
    app.dependency_overrides.clear()


SAMPLE_ROW = {
    "Report ID": "RPT-1",
    "Reporting Entity": "Waymo LLC",
    "Incident Date": "2024-03-01",
    "City": "San Francisco",
    "State": "CA",
    "Highest Injury Severity Alleged": "No Apparent Injury",
    "Crash With": "Passenger Car",
}


def test_list_default_orders_by_incident_date_desc_page_one():
    fake = FakeData(items=[SAMPLE_ROW], total=123)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents")
        assert resp.status_code == 200
        body = resp.json()
        assert body["page"] == 1
        assert body["page_size"] == 50
        assert body["total"] == 123
        call = fake.calls["fetch_incidents"]
        # Typed DATE column — not the raw '"Incident Date"' text, which sorts
        # 'SEP-2025' above 'MAR-2026' alphabetically.
        assert call["order_column"] == "incident_date"
        assert call["direction"] == "DESC"
        assert call["offset"] == 0
        assert call["limit"] == 50
    finally:
        _clear()


def test_list_sort_entity_asc_resolves_reporting_entity():
    fake = FakeData(items=[], total=0)
    _use(fake)
    try:
        with TestClient(app) as client:
            client.get("/incidents?sort=entity&dir=asc")
        call = fake.calls["fetch_incidents"]
        assert call["order_column"] == '"Reporting Entity"'
        assert call["direction"] == "ASC"
    finally:
        _clear()


def test_list_sort_severity_resolves_severity_column():
    fake = FakeData(items=[], total=0)
    _use(fake)
    try:
        with TestClient(app) as client:
            client.get("/incidents?sort=severity")
        assert fake.calls["fetch_incidents"]["order_column"] == '"Highest Injury Severity Alleged"'
    finally:
        _clear()


def test_list_out_of_set_sort_falls_back_to_default():
    fake = FakeData(items=[], total=0)
    _use(fake)
    try:
        with TestClient(app) as client:
            client.get("/incidents?sort=DROP TABLE&dir=sideways")
        call = fake.calls["fetch_incidents"]
        # Falls back to the default column + direction — the malicious string
        # never reaches ORDER BY.
        assert call["order_column"] == "incident_date"
        assert call["direction"] == "DESC"
    finally:
        _clear()


def test_list_page_two_produces_offset_fifty():
    fake = FakeData(items=[], total=0)
    _use(fake)
    try:
        with TestClient(app) as client:
            client.get("/incidents?page=2")
        assert fake.calls["fetch_incidents"]["offset"] == 50
    finally:
        _clear()


def test_list_item_carries_report_id_and_raw_severity_string():
    fake = FakeData(items=[SAMPLE_ROW], total=1)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents")
        item = resp.json()["items"][0]
        assert item["report_id"] == "RPT-1"
        # RAW string, not a bucket label like "No Injuries".
        assert item["severity"] == "No Apparent Injury"
        assert item["crash_with"] == "Passenger Car"
    finally:
        _clear()


DETAIL_ROW = {
    "Report ID": "RPT-9",
    "Reporting Entity": "Cruise LLC",
    "Operating Entity": "Cruise LLC",
    "Incident Date": "2024-05-10",
    "Incident Time": "14:30",
    "City": "Phoenix",
    "State": "AZ",
    "Roadway Type": "Intersection",
    "Roadway Description": "Four-way signalized",
    "Crash With": "Passenger Car",
    "Highest Injury Severity Alleged": "Minor",
    "Property Damage?": "Yes",
    "CP Pre-Crash Movement": "Stopped",
    "SV Pre-Crash Movement": "Proceeding straight",
    "SV Were All Passengers Belted?": "Yes",
    "SV Precrash Speed (MPH)": "12",
    "Law Enforcement Investigating?": "No",
    "CP Contact Area - Front": "Yes",
    "CP Contact Area - Rear": "No",
    "SV Contact Area - Left": "Yes",
    "SV Contact Area - Right": "",
    "Narrative": "The SV was struck while stopped at the light.",
}


def test_detail_returns_full_one_pager_with_collapsed_contact_areas():
    fake = FakeData(detail=DETAIL_ROW)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/RPT-9")
        assert resp.status_code == 200
        body = resp.json()
        assert body["report_id"] == "RPT-9"
        assert body["city"] == "Phoenix"
        assert body["severity"] == "Minor"
        assert body["sv_pre_crash_movement"] == "Proceeding straight"
        assert body["narrative"].startswith("The SV was struck")
        # Truthy contact-area columns collapse to a list; falsey ones drop out.
        assert body["cp_contact_areas"] == ["Front"]
        assert body["sv_contact_areas"] == ["Left"]
        assert fake.calls["fetch_incident"] == "RPT-9"
    finally:
        _clear()


def test_detail_with_same_incident_id_lists_other_reports():
    row = dict(DETAIL_ROW, **{"Same Incident ID": "abc123"})
    others = [{"Report ID": "RPT-10", "Reporting Entity": "Waymo LLC"}]
    fake = FakeData(detail=row, others=others)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/RPT-9")
        body = resp.json()
        assert body["other_reports"] == [{"report_id": "RPT-10", "reporting_entity": "Waymo LLC"}]
        assert fake.calls["fetch_other_reports"] == {
            "same_incident_id": "abc123",
            "report_id": "RPT-9",
        }
    finally:
        _clear()


def test_detail_without_same_incident_id_skips_lookup_and_returns_empty():
    fake = FakeData(detail=dict(DETAIL_ROW, **{"Same Incident ID": "  "}))
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/RPT-9")
        assert resp.json()["other_reports"] == []
        assert "fetch_other_reports" not in fake.calls
    finally:
        _clear()


def test_detail_unknown_report_id_returns_404():
    fake = FakeData(detail=None)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/nope")
        assert resp.status_code == 404
    finally:
        _clear()


def test_no_write_routes_on_incidents():
    fake = FakeData(items=[], total=0)
    _use(fake)
    try:
        with TestClient(app) as client:
            assert client.post("/incidents").status_code == 405
            assert client.delete("/incidents/RPT-1").status_code == 405
            assert client.put("/incidents/RPT-1").status_code == 405
    finally:
        _clear()


# --- Data-layer SQL tests via fake pool ------------------------------------


class _FakeConn:
    def __init__(self, *, fetch=None, fetchval=0, fetchrow=None):
        self._fetch = fetch if fetch is not None else []
        self._fetchval = fetchval
        self._fetchrow = fetchrow
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        return self._fetch

    async def fetchval(self, query, *args):
        self.queries.append((query, args))
        return self._fetchval

    async def fetchrow(self, query, *args):
        self.queries.append((query, args))
        return self._fetchrow


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


async def test_list_query_has_no_canonical_clause_and_offsets(monkeypatch):
    conn = _FakeConn(fetch=[])
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_incidents(
        limit=50, offset=50, order_column="incident_date", direction="DESC"
    )
    query, args = conn.queries[0]
    assert data_module.CANONICAL_CLAUSE not in query
    assert "is_latest_of_multiple_report" not in query
    assert "NULLS LAST" in query
    assert args == (50, 50)


async def test_other_reports_query_parameterizes_and_excludes_self(monkeypatch):
    conn = _FakeConn(fetch=[])
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_other_reports("sid-1", "RPT-9")
    query, args = conn.queries[0]
    assert args == ("sid-1", "RPT-9")
    assert '"Same Incident ID" = $1' in query
    assert '"Report ID" <> $2' in query


async def test_count_query_is_unfiltered(monkeypatch):
    conn = _FakeConn(fetchval=999)
    _patch_pool(monkeypatch, conn)
    total = await IncidentData().count_incidents()
    query, _ = conn.queries[0]
    assert total == 999
    assert "WHERE" not in query.upper()


async def test_detail_query_parameterizes_report_id_no_canonical(monkeypatch):
    conn = _FakeConn(fetchrow={"Report ID": "X"})
    _patch_pool(monkeypatch, conn)
    await IncidentData().fetch_incident("X")
    query, args = conn.queries[0]
    assert args == ("X",)
    assert "is_latest_of_multiple_report" not in query
