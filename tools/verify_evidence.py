"""Deterministic gate logic for local web verification — the shared module.

Owns every rule the verification gate needs: route inventory, file→route
mapping, pending bookkeeping, evidence recording, and freshness checking.
The Claude Code hooks (.claude/hooks/) and the /verify-local command both
call this; nothing else reimplements its rules.

Subcommands:
    routes                      list all routes (globbed from apps/web/app)
    affected <file>             routes a file affects (shared files → all)
    pending-add <file>          mark a file as pending verification (no-op
                                for paths that affect no route)
    pending-routes              routes the gate currently wants verified
    pending-clear               explicit write-off of all pending debt —
                                user-invoked only; the agent never runs it
                                silently
    record --route R --screenshot P --console-errors N --result pass|fail
                                write evidence JSON with content hashes of
                                every file affecting the route
    check [--clear-satisfied]   the gate decision: every pending route needs
                                evidence that exists, passed, references a
                                real screenshot, and matches current file
                                hashes. Exit 1 + actionable message otherwise.

State lives in gitignored .verify/ (pending.json, evidence/, screenshots/).
Pending entries persist across sessions by design — verification debt is
inherited, not forgiven (see the plan, KTD 5).

Freshness is content-hashed, not timestamped: evidence records a blob-style
sha1 of each affecting file's raw working-tree bytes; check recomputes and
any mismatch is stale. (Computed in-process rather than via `git
hash-object` so results never depend on git's CRLF filters and the hooks
stay subprocess-free; the hashes are only ever compared to themselves.)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# === Mapping rules — the one obvious place (edit here when conventions change) ===

# Root of the Next.js App Router tree, repo-relative.
WEB_APP_DIR = "apps/web/app"
# A file with this name defines a route at its directory path.
PAGE_FILENAME = "page.tsx"
# Files whose name contains this marker never affect a route.
TEST_MARKER = ".test."
# Where all verification state lives (gitignored).
VERIFY_DIR = ".verify"

# === / ===


def _rel_posix(file_path: str | Path, repo_root: Path) -> str | None:
    """Normalize any incoming path to a repo-relative posix string, or None
    if it falls outside the repo."""
    p = Path(file_path)
    if p.is_absolute():
        try:
            p = p.relative_to(repo_root)
        except ValueError:
            return None
    return p.as_posix()


def classify(rel_path: str) -> str:
    """'page' | 'shared' | 'none' for a repo-relative posix path.

    Purely path-based — the file need not exist (a deleted shared file
    still affects every route).
    """
    if not rel_path.startswith(WEB_APP_DIR + "/"):
        return "none"
    name = rel_path.rsplit("/", 1)[-1]
    if TEST_MARKER in name:
        return "none"
    if name == PAGE_FILENAME:
        return "page"
    return "shared"


def route_for_page(rel_path: str) -> str:
    """apps/web/app/<segs>/page.tsx → /<segs>; apps/web/app/page.tsx → /."""
    inner = rel_path[len(WEB_APP_DIR) + 1 :]  # strip "apps/web/app/"
    segs = inner.split("/")[:-1]  # drop page.tsx
    return "/" + "/".join(segs) if segs else "/"


def route_inventory(repo_root: Path) -> dict[str, str]:
    """All current routes → their page file (repo-relative posix)."""
    app_dir = repo_root / WEB_APP_DIR
    out: dict[str, str] = {}
    for page in sorted(app_dir.rglob(PAGE_FILENAME)):
        rel = page.relative_to(repo_root).as_posix()
        if classify(rel) == "page":
            out[route_for_page(rel)] = rel
    return out


def shared_files(repo_root: Path) -> list[str]:
    """All current files that affect every route (repo-relative posix)."""
    app_dir = repo_root / WEB_APP_DIR
    out = []
    for f in sorted(app_dir.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(repo_root).as_posix()
        if classify(rel) == "shared":
            out.append(rel)
    return out


def affected_routes(file_path: str | Path, repo_root: Path) -> list[str]:
    """Routes a file affects. Page files → their route (even if since
    deleted — callers intersect with the inventory). Shared files → all
    current routes. Everything else → none."""
    rel = _rel_posix(file_path, repo_root)
    if rel is None:
        return []
    kind = classify(rel)
    if kind == "page":
        return [route_for_page(rel)]
    if kind == "shared":
        return sorted(route_inventory(repo_root))
    return []


def affecting_files(route: str, repo_root: Path) -> list[str]:
    """Every current file whose content the route's evidence must pin:
    the route's own page file plus all shared files."""
    inventory = route_inventory(repo_root)
    files = list(shared_files(repo_root))
    if route in inventory:
        files.append(inventory[route])
    return sorted(files)


def blob_hash(path: Path) -> str:
    """Git-blob-style sha1 over raw bytes (no CRLF filtering — see module
    docstring)."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# --- pending bookkeeping -----------------------------------------------------


def _pending_path(repo_root: Path) -> Path:
    return repo_root / VERIFY_DIR / "pending.json"


def load_pending(repo_root: Path) -> list[str]:
    p = _pending_path(repo_root)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    files = data.get("files", [])
    return files if isinstance(files, list) else []


def save_pending(repo_root: Path, files: list[str]) -> None:
    p = _pending_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"files": sorted(set(files))}, indent=2), encoding="utf-8")


def pending_add(file_path: str | Path, repo_root: Path = REPO_ROOT) -> bool:
    """Mark a file pending if it affects any route. Returns True if it was
    page-affecting (added or already present), False for a no-op."""
    rel = _rel_posix(file_path, repo_root)
    if rel is None or classify(rel) == "none":
        return False
    files = load_pending(repo_root)
    if rel not in files:
        files.append(rel)
        save_pending(repo_root, files)
    return True


def pending_routes(repo_root: Path) -> list[str]:
    """Union of routes across pending files, limited to routes that still
    exist (a deleted page's debt dies with its route)."""
    inventory = route_inventory(repo_root)
    routes: set[str] = set()
    for f in load_pending(repo_root):
        routes.update(r for r in affected_routes(f, repo_root) if r in inventory)
    return sorted(routes)


# --- evidence ----------------------------------------------------------------


def _evidence_name(route: str) -> str:
    """Filesystem-safe evidence/screenshot stem for a route template.
    The root route gets a sentinel no real segment can produce, so a future
    /root route cannot collide with it."""
    return route.strip("/").replace("/", "__") or "__root__"


def evidence_path(route: str, repo_root: Path) -> Path:
    return repo_root / VERIFY_DIR / "evidence" / f"{_evidence_name(route)}.json"


def record_evidence(
    route: str,
    screenshot: str,
    console_errors: int,
    result: str,
    repo_root: Path = REPO_ROOT,
    sample_url: str | None = None,
) -> Path:
    """Write the evidence record for a route, pinning current content hashes
    of every affecting file. The screenshot must already exist — evidence
    without observable proof is a claim, not evidence."""
    shot = Path(screenshot)
    shot_abs = shot if shot.is_absolute() else repo_root / shot
    if not shot_abs.exists():
        raise FileNotFoundError(f"screenshot does not exist: {screenshot}")

    hashes = {}
    for rel in affecting_files(route, repo_root):
        f = repo_root / rel
        if f.exists():
            hashes[rel] = blob_hash(f)

    record = {
        "route": route,
        "sample_url": sample_url,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "console_errors": console_errors,
        "screenshot": _rel_posix(shot_abs, repo_root) or str(shot_abs),
        "file_hashes": hashes,
    }
    out = evidence_path(route, repo_root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return out


# --- the gate decision --------------------------------------------------------


@dataclass
class RouteCheck:
    route: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        prefix = "[ok]" if self.ok else "[fail]"
        suffix = f" — {self.detail}" if self.detail else ""
        return f"{prefix} {self.route}{suffix}"


def check_route(route: str, repo_root: Path) -> RouteCheck:
    """One route's gate decision: evidence exists, passed, screenshot file
    exists, and content hashes match the current working tree exactly."""
    ev_path = evidence_path(route, repo_root)
    if not ev_path.exists():
        return RouteCheck(route, False, "no evidence recorded")
    try:
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return RouteCheck(route, False, "evidence unreadable")

    if ev.get("result") != "pass":
        return RouteCheck(route, False, f"last verification result: {ev.get('result')}")

    shot = ev.get("screenshot")
    if not shot or not (repo_root / shot).exists():
        return RouteCheck(route, False, "screenshot missing")

    recorded: dict = ev.get("file_hashes") or {}
    current: dict = {}
    for rel in affecting_files(route, repo_root):
        f = repo_root / rel
        if f.exists():
            current[rel] = blob_hash(f)
    if recorded != current:
        changed = sorted(
            (set(recorded) ^ set(current))
            | {k for k in set(recorded) & set(current) if recorded[k] != current[k]}
        )
        return RouteCheck(route, False, f"stale — changed since verification: {', '.join(changed)}")

    return RouteCheck(route, True, "fresh passing evidence")


def check(
    repo_root: Path = REPO_ROOT, clear_satisfied: bool = False
) -> tuple[list[RouteCheck], bool]:
    """The full gate decision over pending debt. Returns (per-route results,
    all_ok). With clear_satisfied, pending entries whose routes all pass are
    removed; blocked entries stay."""
    pending = load_pending(repo_root)
    if not pending:
        return [], True

    inventory = route_inventory(repo_root)
    results: dict[str, RouteCheck] = {}
    still_pending: list[str] = []
    for f in pending:
        routes = [r for r in affected_routes(f, repo_root) if r in inventory]
        file_ok = True
        for r in routes:
            if r not in results:
                results[r] = check_route(r, repo_root)
            if not results[r].ok:
                file_ok = False
        # A pending file with zero surviving routes (deleted page) is satisfied.
        if not file_ok:
            still_pending.append(f)

    if clear_satisfied:
        save_pending(repo_root, still_pending)

    ordered = [results[r] for r in sorted(results)]
    return ordered, not still_pending


def block_message(results: list[RouteCheck]) -> str:
    """Actionable block text naming exactly what to run."""
    failed = [r for r in results if not r.ok]
    lines = [r.line() for r in results]
    lines.append("")
    lines.append("Unverified web changes — run the local verification loop before finishing:")
    for r in failed:
        lines.append(f"  /verify-local {r.route}")
    return "\n".join(lines)


def _looks_filesystem_mangled(route: str) -> bool:
    """True when a route value is clearly a Windows filesystem path — the
    signature of MSYS/Git-Bash argument conversion, never a real route."""
    return len(route) >= 3 and route[0].isalpha() and route[1] == ":" and route[2] in "/\\"


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root",
        help="Override the repo root (testing); must precede the subcommand.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("routes", help="list all routes")
    p_aff = sub.add_parser("affected", help="routes a file affects")
    p_aff.add_argument("file")
    p_add = sub.add_parser("pending-add", help="mark a file pending verification")
    p_add.add_argument("file")
    sub.add_parser("pending-routes", help="routes the gate currently wants")
    sub.add_parser(
        "pending-clear",
        help="explicit write-off of all pending debt (user-invoked only)",
    )
    p_rec = sub.add_parser("record", help="write evidence for a verified route")
    p_rec.add_argument("--route", required=True)
    p_rec.add_argument("--screenshot", required=True)
    p_rec.add_argument("--console-errors", type=int, required=True)
    p_rec.add_argument("--result", choices=["pass", "fail"], required=True)
    p_rec.add_argument("--sample-url", help="concrete URL used for a dynamic route template")
    p_chk = sub.add_parser("check", help="the gate decision over pending debt")
    p_chk.add_argument("--clear-satisfied", action="store_true")

    args = parser.parse_args(argv)
    repo_root = Path(args.repo_root).resolve() if args.repo_root else REPO_ROOT

    if args.cmd == "routes":
        for r in sorted(route_inventory(repo_root)):
            print(r)
        return 0

    if args.cmd == "affected":
        for r in affected_routes(args.file, repo_root):
            print(r)
        return 0

    if args.cmd == "pending-add":
        pending_add(args.file, repo_root)
        return 0

    if args.cmd == "pending-routes":
        for r in pending_routes(repo_root):
            print(r)
        return 0

    if args.cmd == "pending-clear":
        n = len(load_pending(repo_root))
        save_pending(repo_root, [])
        print(f"[ok] cleared {n} pending entr{'y' if n == 1 else 'ies'}")
        return 0

    if args.cmd == "record":
        # Git Bash (MSYS) rewrites leading-slash args into filesystem paths
        # ("/about" -> "C:/Program Files/Git/about"). Reject the mangled form
        # loudly and accept the slash-less form as the documented shape.
        if _looks_filesystem_mangled(args.route):
            print(
                f"[fail] route '{args.route}' looks like a shell-mangled filesystem path "
                f"(Git Bash converts leading-slash arguments). Pass the route without the "
                f"leading slash, e.g. --route about",
                file=sys.stderr,
            )
            return 2
        # "." is the root-route alias (a bare "/" gets mangled by Git Bash too).
        # Strip only the leading slash — a dotted segment (.well-known) is legal.
        if args.route in (".", "/", ""):
            args.route = "/"
        elif not args.route.startswith("/"):
            args.route = "/" + args.route
        try:
            out = record_evidence(
                args.route,
                args.screenshot,
                args.console_errors,
                args.result,
                repo_root,
                sample_url=args.sample_url,
            )
        except FileNotFoundError as exc:
            print(f"[fail] {exc}", file=sys.stderr)
            return 2
        # ASCII arrow: Windows consoles default to cp1252, which can't encode U+2192
        print(
            f"[ok] recorded {args.result} evidence for {args.route} -> {out.relative_to(repo_root)}"
        )
        return 0

    if args.cmd == "check":
        results, ok = check(repo_root, clear_satisfied=args.clear_satisfied)
        if not results and ok:
            return 0  # empty pending: silent pass
        if ok:
            for r in results:
                print(r.line())
            return 0
        print(block_message(results))
        return 1

    return 2  # unreachable


if __name__ == "__main__":
    sys.exit(main())
