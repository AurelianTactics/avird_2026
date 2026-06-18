"""Agent-runnable site-verification harness for avird-2026.

Three checks against the deployed public web origin:

  1. status        — GET /, /about, and /groupings all return 200
  2. internal links — all same-origin <a href> values from those pages return 200
                      (incl. the per-incident detail links the list renders)
  3. expected text  — each page renders its stable needle; a page that loads but
                      shows a data-failure notice ("Could not load ...") fails

Output is a punch list, one line per check, prefixed [ok] or [fail], plus a
final summary count. Non-zero exit on any failure.

Usage:
    python tools/verify_site.py --base-url https://avird-2026.up.railway.app

Local fixture tests live in tools/tests/test_verify_site.py.
The slash command at .claude/commands/verify-site.md wraps this script.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

# === Assertion config — edit when site content changes ===

# Required substrings per page. Extend by adding pages or strings. Each needle
# is a stable fragment the page always renders regardless of data state (prose
# intro, not table contents) so the gate is robust to an empty result set.
EXPECTED_TEXT: dict[str, list[str]] = {
    "/": ["Raw NHTSA SGO crash reports"],
    "/about": ["autonomous-vehicle crash data"],
    "/groupings": ["Canonical (deduplicated) crash counts"],
}

# Pages whose status code is asserted, and whose internal links are crawled.
# Detail pages need no needle here — the list renders real <a href> detail
# links, so the internal-link crawler reaches and 200-checks them.
PAGES_TO_CHECK: list[str] = list(EXPECTED_TEXT.keys())

# Per-page strings that mean the page rendered (200) but its data layer failed —
# explicit failures even though the page itself loaded. Replaces the old
# index-only "API: down/unreachable" check now that / is the data-backed list.
DEGRADED_TEXT: dict[str, list[str]] = {
    "/": ["Could not load incidents"],
    "/groupings": ["Could not load groupings"],
}

# === / ===


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        prefix = "[ok]" if self.ok else "[fail]"
        suffix = f": {self.detail}" if self.detail else ""
        return f"{prefix} {self.name}{suffix}"


def _is_internal_href(href: str, page_url: str) -> bool:
    if not href:
        return False
    if href.startswith(("mailto:", "tel:", "javascript:")):
        return False
    href_parsed = urlparse(href)
    page_parsed = urlparse(page_url)
    if not href_parsed.netloc:
        return True
    return href_parsed.netloc == page_parsed.netloc


def _collect_internal_links(html: str, page_url: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _is_internal_href(href, page_url):
            continue
        absolute = urljoin(page_url, href).split("#")[0]
        if absolute:
            out.add(absolute)
    return out


def verify(base_url: str, *, client: httpx.Client) -> list[Result]:
    base = base_url.rstrip("/")
    results: list[Result] = []
    pages: dict[str, httpx.Response] = {}

    # 1. Status on each known page
    for path in PAGES_TO_CHECK:
        url = base + path
        try:
            resp = client.get(url, follow_redirects=True)
            pages[path] = resp
            ok = resp.status_code == 200
            results.append(Result(f"status {path}", ok, str(resp.status_code)))
        except httpx.HTTPError as exc:
            results.append(Result(f"status {path}", False, f"{type(exc).__name__}: {exc}"))

    # 2. Internal links from those pages
    known = {(base + p).rstrip("/") for p in PAGES_TO_CHECK}
    discovered: set[str] = set()
    for path, resp in pages.items():
        if resp.status_code != 200:
            continue
        for link in _collect_internal_links(resp.text, str(resp.url)):
            if link.rstrip("/") in known:
                continue
            discovered.add(link)

    for link in sorted(discovered):
        try:
            resp = client.get(link, follow_redirects=True)
            ok = resp.status_code == 200
            results.append(Result(f"link {link}", ok, str(resp.status_code)))
        except httpx.HTTPError as exc:
            results.append(Result(f"link {link}", False, f"{type(exc).__name__}: {exc}"))

    # 3. Expected text per page; reject degraded states on the index.
    # Match against the rendered text content, not raw HTML. React SSR
    # inserts empty marker comments (e.g. `API: <!-- -->ok`) between
    # static and dynamic text — those break naive substring search on
    # raw HTML even though the browser renders the expected string.
    for path, needles in EXPECTED_TEXT.items():
        resp = pages.get(path)
        if resp is None or resp.status_code != 200:
            results.append(Result(f"text {path}", False, "page did not load"))
            continue
        text = BeautifulSoup(resp.text, "html.parser").get_text()
        for needle in needles:
            ok = needle in text
            results.append(Result(f"text {path} '{needle}'", ok, "" if ok else "missing"))
        for degraded in DEGRADED_TEXT.get(path, []):
            if degraded in text:
                results.append(
                    Result(
                        f"text {path} not-degraded '{degraded}'",
                        False,
                        "found degraded state",
                    )
                )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the deployed avird-2026 site (status, links, expected text)."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="Public web URL, e.g. https://avird-2026.up.railway.app",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds (default: 10).",
    )
    args = parser.parse_args(argv)

    with httpx.Client(timeout=args.timeout) as client:
        results = verify(args.base_url, client=client)

    for r in results:
        print(r.line())
    failed = [r for r in results if not r.ok]
    print()
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
