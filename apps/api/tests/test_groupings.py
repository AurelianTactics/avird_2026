"""Tests for the treated entity x severity groupings route (U4, covers R5).

Route tests override `get_incident_data` with a fake returning raw
`(master_entity, raw_severity, n)` rows and assert the pivot, bucket order,
zero-fill, and totals. A data-layer SQL test proves the aggregate query
applies the canonical clause (the treated side keeps dedup).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import data as data_module
from app.data import IncidentData
from app.groupings import get_incident_data
from app.main import app
from app.severity import BUCKET_ORDER


class FakeData:
    def __init__(self, counts):
        self._counts = counts

    async def fetch_entity_severity_counts(self):
        return self._counts


def _use(counts):
    app.dependency_overrides[get_incident_data] = lambda: FakeData(counts)


def _clear():
    app.dependency_overrides.clear()


def test_one_row_per_entity_zero_filled_buckets():
    _use(
        [
            {"master_entity": "Waymo", "raw_severity": "Fatality", "n": 2},
            {"master_entity": "Waymo", "raw_severity": "Minor", "n": 5},
            {"master_entity": "Cruise", "raw_severity": "No Apparent Injury", "n": 3},
        ]
    )
    try:
        with TestClient(app) as client:
            body = client.get("/groupings/entity-severity").json()
    finally:
        _clear()

    by_entity = {r["entity"]: r for r in body["rows"]}
    assert set(by_entity) == {"Waymo", "Cruise"}
    # Every row has all seven buckets, zero-filled.
    for row in body["rows"]:
        assert set(row["counts"]) == set(BUCKET_ORDER)
    assert by_entity["Waymo"]["counts"]["Fatality"] == 2
    assert by_entity["Waymo"]["counts"]["Minor"] == 5
    assert by_entity["Waymo"]["counts"]["Serious"] == 0
    assert by_entity["Cruise"]["counts"]["No Injuries"] == 3


def test_per_entity_total_is_sum_of_buckets():
    _use(
        [
            {"master_entity": "Waymo", "raw_severity": "Fatality", "n": 2},
            {"master_entity": "Waymo", "raw_severity": "Minor", "n": 5},
        ]
    )
    try:
        with TestClient(app) as client:
            body = client.get("/groupings/entity-severity").json()
    finally:
        _clear()
    assert body["rows"][0]["total"] == 7


def test_unmapped_severity_buckets_to_unknown_not_dropped():
    _use([{"master_entity": "Waymo", "raw_severity": "Catastrophic", "n": 4}])
    try:
        with TestClient(app) as client:
            body = client.get("/groupings/entity-severity").json()
    finally:
        _clear()
    row = body["rows"][0]
    assert row["counts"]["Unknown"] == 4
    assert row["total"] == 4


def test_buckets_is_the_seven_label_ordered_constant():
    _use([])
    try:
        with TestClient(app) as client:
            body = client.get("/groupings/entity-severity").json()
    finally:
        _clear()
    assert body["buckets"] == BUCKET_ORDER


def test_empty_result_yields_empty_rows_with_buckets_present():
    _use([])
    try:
        with TestClient(app) as client:
            body = client.get("/groupings/entity-severity").json()
    finally:
        _clear()
    assert body["rows"] == []
    assert body["buckets"] == BUCKET_ORDER


def test_rows_sorted_by_total_desc():
    _use(
        [
            {"master_entity": "Small", "raw_severity": "Minor", "n": 1},
            {"master_entity": "Big", "raw_severity": "Minor", "n": 10},
        ]
    )
    try:
        with TestClient(app) as client:
            body = client.get("/groupings/entity-severity").json()
    finally:
        _clear()
    assert [r["entity"] for r in body["rows"]] == ["Big", "Small"]


# --- Data-layer SQL test ----------------------------------------------------


class _FakeConn:
    def __init__(self, fetch):
        self._fetch = fetch
        self.queries: list[tuple[str, tuple]] = []

    async def fetch(self, query, *args):
        self.queries.append((query, args))
        return self._fetch


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


async def test_groupings_query_applies_canonical_clause(monkeypatch):
    conn = _FakeConn(fetch=[])

    async def _get_pool():
        return _FakePool(conn)

    monkeypatch.setattr(data_module, "get_pool", _get_pool)
    await IncidentData().fetch_entity_severity_counts()
    query, _ = conn.queries[0]
    # The treated side keeps dedup even though the raw list dropped it.
    assert data_module.CANONICAL_CLAUSE in query
    assert "is_latest_of_multiple_report" in query
