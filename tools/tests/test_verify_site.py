"""Tests for tools/verify_site.py against a local WSGI fixture.

The fixture serves stub HTML for "/" and "/about" via httpx.WSGITransport,
so the harness exercises real HTTP semantics (status codes, headers,
redirect handling) without touching the network.
"""

from __future__ import annotations

import httpx
import pytest

from verify_site import verify

HEALTHY_INDEX = """<!DOCTYPE html>
<html><body>
<main>
  <h1>avird-2026</h1>
  <p>API: ok</p>
  <nav><a href="/about">About</a></nav>
</main>
</body></html>"""

ABOUT_PAGE = """<!DOCTYPE html>
<html><body>
<main>
  <h1>About this project</h1>
  <nav><a href="/">Home</a></nav>
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
    return {"/": (200, HEALTHY_INDEX), "/about": (200, ABOUT_PAGE)}


def test_all_checks_pass_against_healthy_fixture(healthy_routes):
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    assert all(r.ok for r in results), [r.line() for r in results if not r.ok]


def test_fails_when_about_returns_500(healthy_routes):
    healthy_routes["/about"] = (500, "boom")
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("status /about" in r.name and "500" in r.detail for r in failed)


def test_fails_when_internal_link_404s(healthy_routes):
    healthy_routes["/"] = (200, HEALTHY_INDEX.replace('href="/about"', 'href="/missing"'))
    # /missing intentionally absent from routes -> WSGI returns 404
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("/missing" in r.name and "404" in r.detail for r in failed)


def test_fails_when_index_renders_degraded_down_state(healthy_routes):
    healthy_routes["/"] = (200, HEALTHY_INDEX.replace("API: ok", "API: down"))
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("'API: ok'" in r.name and r.detail == "missing" for r in failed)
    assert any("'API: down'" in r.name and "found degraded" in r.detail for r in failed)


def test_fails_when_index_renders_unreachable(healthy_routes):
    healthy_routes["/"] = (200, HEALTHY_INDEX.replace("API: ok", "API: unreachable"))
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("'API: unreachable'" in r.name and "found degraded" in r.detail for r in failed)


def test_fails_when_expected_text_missing_entirely(healthy_routes):
    healthy_routes["/"] = (200, HEALTHY_INDEX.replace("API: ok", ""))
    with _client(healthy_routes) as client:
        results = verify("http://test", client=client)
    failed = [r for r in results if not r.ok]
    assert any("'API: ok'" in r.name and r.detail == "missing" for r in failed)


def test_external_links_not_fetched(healthy_routes):
    healthy_routes["/"] = (
        200,
        HEALTHY_INDEX.replace(
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
