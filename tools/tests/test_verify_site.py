"""Tests for tools/verify_site.py against a local WSGI fixture.

The fixture serves stub HTML for the live routes via httpx.WSGITransport, so
the harness exercises real HTTP semantics (status codes, headers, redirect
handling) without touching the network.

The stubs mirror the W1-W2 pages: / is the raw incident list (with a real
detail <a href> the crawler must reach), /groupings is the treated matrix, and
/about carries the GitHub link.
"""

from __future__ import annotations

import httpx
import pytest

from verify_site import verify

# The raw incident list. Renders the stable intro needle plus a real detail
# link the internal-link crawler should discover and 200-check.
INDEX_PAGE = """<!DOCTYPE html>
<html><body>
<nav><a href="/groupings">Groupings</a><a href="/about">About</a></nav>
<main>
  <h1>Incidents</h1>
  <p>Raw NHTSA SGO crash reports - every reported row, newest first.</p>
  <table><tbody>
    <tr><td><a href="/incidents/RPT-1">2024-03-01</a></td></tr>
  </tbody></table>
</main>
</body></html>"""

GROUPINGS_PAGE = """<!DOCTYPE html>
<html><body>
<nav><a href="/">Incidents</a><a href="/about">About</a></nav>
<main>
  <h1>Groupings</h1>
  <p>Canonical (deduplicated) crash counts by reporting entity and severity.</p>
</main>
</body></html>"""

DETAIL_PAGE = """<!DOCTYPE html>
<html><body>
<main><h1>Cruise LLC</h1><p>Report RPT-1 - raw reported fields.</p></main>
</body></html>"""

ABOUT_PAGE = """<!DOCTYPE html>
<html><body>
<main>
  <h1>About this project</h1>
  <p>Source code:
    <a href="https://github.com/AurelianTactics/avird_2026">repo</a>
  </p>
</main>
</body></html>"""


def _wsgi_app(routes: dict[str, tuple[int, str]]):
    def app(environ, start_response):
        path = environ.get("PATH_INFO", "/")
        if path in routes:
            status_code, body = routes[path]
            start_response(
                f"{status_code} OK",
                [("Content-Type", "text/html; charset=utf-8")],
            )
            return [body.encode("utf-8")]
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return [b"not found"]

    return app


def _client(routes: dict[str, tuple[int, str]]) -> httpx.Client:
    return httpx.Client(
        transport=httpx.WSGITransport(app=_wsgi_app(routes)),
        base_url="http://test",
    )


@pytest.fixture
def healthy_routes() -> dict[str, tuple[int, str]]:
    return {
        "/": (200, INDEX_PAGE),
        "/about": (200, ABOUT_PAGE),
        "/groupings": (200, GROUPINGS_PAGE),
        "/incidents/RPT-1": (200, DETAIL_PAGE),
    }


def test_all_checks_pass_against_healthy_fixture(healthy_routes):
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    assert all(r.ok for r in results), [r.line() for r in results if not r.ok]


def test_index_needle_is_checked(healthy_routes):
    # The new / renders the raw-list intro, not "API: ok".
    healthy_routes["/"] = (200, INDEX_PAGE.replace("Raw NHTSA SGO crash reports", "Welcome"))
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("Raw NHTSA SGO crash reports" in r.name and r.detail == "missing" for r in failed)


def test_groupings_needle_is_checked(healthy_routes):
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    assert any("/groupings" in r.name and "Canonical" in r.name and r.ok for r in results)
    # And a missing needle fails.
    healthy_routes["/groupings"] = (200, GROUPINGS_PAGE.replace("Canonical (deduplicated)", "Some"))
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("/groupings" in r.name and r.detail == "missing" for r in failed)


def test_detail_link_is_discovered_and_checked(healthy_routes):
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    # The list's <a href="/incidents/RPT-1"> is crawled for 200.
    assert any("/incidents/RPT-1" in r.name and r.ok for r in results)


def test_fails_when_detail_link_404s(healthy_routes):
    del healthy_routes["/incidents/RPT-1"]  # crawler now hits a 404
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("/incidents/RPT-1" in r.name and "404" in r.detail for r in failed)


def test_fails_when_about_returns_500(healthy_routes):
    healthy_routes["/about"] = (500, "boom")
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("status /about" in r.name and "500" in r.detail for r in failed)


def test_fails_when_index_renders_data_failure_notice(healthy_routes):
    # Page loads (200) but the data layer failed -> degraded, not green.
    degraded = INDEX_PAGE.replace(
        "<table><tbody>",
        '<p class="notice">Could not load incidents.</p><table><tbody>',
    )
    healthy_routes["/"] = (200, degraded)
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("not-degraded 'Could not load incidents'" in r.name for r in failed)


def test_fails_when_groupings_renders_data_failure_notice(healthy_routes):
    degraded = GROUPINGS_PAGE.replace(
        "</main>", '<p class="notice">Could not load groupings.</p></main>'
    )
    healthy_routes["/groupings"] = (200, degraded)
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("not-degraded 'Could not load groupings'" in r.name for r in failed)


def test_no_longer_requires_api_ok_on_index(healthy_routes):
    # The retired placeholder needle must not be asserted anywhere.
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    assert not any("API: ok" in r.name for r in results)


def test_external_links_not_fetched(healthy_routes):
    healthy_routes["/"] = (
        200,
        INDEX_PAGE.replace(
            "<nav>",
            '<nav><a href="https://example.invalid/broken">External</a>',
        ),
    )
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    assert not any("example.invalid" in r.name for r in results)
    assert all(r.ok for r in results)


def test_about_heading_check(healthy_routes):
    healthy_routes["/about"] = (200, ABOUT_PAGE.replace("About this project", "Untitled"))
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("'About this project'" in r.name and r.detail == "missing" for r in failed)
