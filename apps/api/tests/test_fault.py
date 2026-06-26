"""Tests for the read-only fault route (U covers R4).

Route tests override `get_fault_data` with an in-memory fake — they prove the
response shape, the most-recent-version selection contract, the 404 on a report
with no verdict, and that the error-sentinel row surfaces as null verdict
fields. No live DB, no LLM, no key (mirrors `test_incidents.py`).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.fault import get_fault_data
from app.main import app


class FakeFaultData:
    def __init__(self, *, row=None):
        self.row = row
        self.calls: list[str] = []

    async def fetch_fault(self, report_id):
        self.calls.append(report_id)
        return self.row


def _use(fake: FakeFaultData):
    app.dependency_overrides[get_fault_data] = lambda: fake


def _clear():
    app.dependency_overrides.clear()


VERDICT_ROW = {
    "report_id": "RPT-9",
    "fault_version": "mvp_0.01",
    "is_av_at_fault": True,
    "av_fault_percentage": 0.75,
    "short_explanation_of_decision": "The AV ran a red light.",
    "model": "claude-haiku-4-5",
    "created_at": "2026-06-25T00:00:00+00:00",
}


def test_fault_route_returns_stored_verdict():
    fake = FakeFaultData(row=VERDICT_ROW)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/RPT-9/fault")
        assert resp.status_code == 200
        body = resp.json()
        assert body["report_id"] == "RPT-9"
        assert body["is_av_at_fault"] is True
        assert body["av_fault_percentage"] == 0.75
        assert body["short_explanation"] == "The AV ran a red light."
        assert body["model"] == "claude-haiku-4-5"
        assert body["fault_version"] == "mvp_0.01"
        assert fake.calls == ["RPT-9"]
    finally:
        _clear()


def test_fault_route_404_when_no_verdict():
    fake = FakeFaultData(row=None)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/UNKNOWN/fault")
        assert resp.status_code == 404
    finally:
        _clear()


def test_fault_route_surfaces_error_sentinel_as_nulls():
    sentinel = {
        "report_id": "RPT-2",
        "fault_version": "mvp_0.01",
        "is_av_at_fault": None,
        "av_fault_percentage": None,
        "short_explanation_of_decision": "Error: model did not return a valid verdict.",
        "model": "claude-haiku-4-5",
        "created_at": "2026-06-25T00:00:00+00:00",
    }
    fake = FakeFaultData(row=sentinel)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/RPT-2/fault")
        body = resp.json()
        assert body["is_av_at_fault"] is None
        assert body["av_fault_percentage"] is None
        assert body["short_explanation"].startswith("Error:")
    finally:
        _clear()


def test_fault_route_coerces_decimal_percentage_to_float():
    from decimal import Decimal

    row = dict(VERDICT_ROW, av_fault_percentage=Decimal("0.5000"))
    fake = FakeFaultData(row=row)
    _use(fake)
    try:
        with TestClient(app) as client:
            resp = client.get("/incidents/RPT-9/fault")
        assert resp.json()["av_fault_percentage"] == 0.5
    finally:
        _clear()


def test_no_write_routes_on_fault():
    fake = FakeFaultData(row=VERDICT_ROW)
    _use(fake)
    try:
        with TestClient(app) as client:
            assert client.post("/incidents/RPT-9/fault").status_code == 405
            assert client.delete("/incidents/RPT-9/fault").status_code == 405
    finally:
        _clear()
