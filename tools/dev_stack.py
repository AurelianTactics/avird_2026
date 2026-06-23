"""Local dev-stack orchestration: api (:8000) + web (:3000), Windows-first.

One command brings both services up against the seeded local database with
the prod env contract (DATABASE_URL, API_URL); one reports health; one tears
down. The substrate for the /verify-local loop.

Subcommands:
    up        spawn api (python -m uvicorn, per the Railway-gotchas learning)
              and web (npm run dev) as detached processes, record PIDs in
              .verify/pids.json, poll until healthy, print a status block.
              Already-running services are reported, never double-spawned.
    status    one [ok]/[fail] line per service (api line includes the db
              state from /health, so "api up but db down" is visible
              immediately); exit non-zero when either is down.
    down      taskkill /T the recorded PID trees, clear the pidfile. A stale
              pidfile (process already gone) is cleaned up silently.

Env files are loaded with a simple KEY=value parser (both apps read plain
os.environ); already-set environment variables win over .env values.
Service logs land in .verify/logs/{api,web}.log.

Usage:
    python tools/dev_stack.py up
    python tools/dev_stack.py status
    python tools/dev_stack.py down
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]

API_PORT = 8000
WEB_PORT = 3000
API_HEALTH_URL = f"http://localhost:{API_PORT}/health"
WEB_URL = f"http://localhost:{WEB_PORT}"
VERIFY_DIR = ".verify"
POLL_INTERVAL = 1.0


@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""

    def line(self) -> str:
        prefix = "[ok]" if self.ok else "[fail]"
        suffix = f": {self.detail}" if self.detail else ""
        return f"{prefix} {self.name}{suffix}"


# --- env handling -------------------------------------------------------------


def parse_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=value parser: comments and blank lines ignored, optional
    surrounding quotes stripped. Both apps read plain os.environ, so no
    interpolation or export syntax is supported (none is used)."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def merge_env(environ: dict[str, str], *parsed: dict[str, str]) -> dict[str, str]:
    """Overlay .env values onto a copy of the environment without overriding
    keys the environment already sets."""
    merged = dict(environ)
    for env_file in parsed:
        for key, value in env_file.items():
            merged.setdefault(key, value)
    return merged


# --- health -------------------------------------------------------------------


def default_http_get(url: str, timeout: float = 5.0) -> tuple[int, str]:
    """GET url → (status_code, body). Connection failure → (0, error text)."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        return resp.status_code, resp.text
    except httpx.HTTPError as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def service_status(http_get=default_http_get) -> tuple[list[Result], bool]:
    """One probe per service. The api line carries the db state from /health
    so a data-layer blocker is visible separately from a dead service."""
    results: list[Result] = []

    status, body = http_get(API_HEALTH_URL)
    if status == 200:
        try:
            db_state = json.loads(body).get("db", "?")
        except (json.JSONDecodeError, AttributeError):
            db_state = "?"
        results.append(Result(f"api :{API_PORT}", True, f"db: {db_state}"))
    else:
        results.append(Result(f"api :{API_PORT}", False, body if status == 0 else f"HTTP {status}"))

    status, body = http_get(WEB_URL)
    if status == 200:
        results.append(Result(f"web :{WEB_PORT}", True))
    else:
        results.append(Result(f"web :{WEB_PORT}", False, body if status == 0 else f"HTTP {status}"))

    return results, all(r.ok for r in results)


def wait_healthy(
    url: str,
    timeout: float,
    http_get=default_http_get,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> bool:
    """Poll url until 200 or timeout."""
    deadline = monotonic() + timeout
    while True:
        status, _ = http_get(url)
        if status == 200:
            return True
        if monotonic() >= deadline:
            return False
        sleep(POLL_INTERVAL)


# --- process management ---------------------------------------------------------


def _pids_path(repo_root: Path) -> Path:
    return repo_root / VERIFY_DIR / "pids.json"


def load_pids(repo_root: Path) -> dict[str, int]:
    p = _pids_path(repo_root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k: int(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError, TypeError, ValueError):
        return {}


def save_pids(repo_root: Path, pids: dict[str, int]) -> None:
    p = _pids_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pids, indent=2), encoding="utf-8")


def api_python() -> str:
    """Interpreter for the api spawn. dev_stack may itself be run by any
    Python (the agent's `python` is often the system one), but uvicorn +
    asyncpg live in the shared app venv documented in stack.md — prefer it
    explicitly over sys.executable.

    Precedence: AVIRD_APP_PYTHON env var > the documented shared-venv path >
    sys.executable (last resort: whoever ran us)."""
    candidates = [
        os.environ.get("AVIRD_APP_PYTHON"),
        str(Path.home() / "claude_code_repos/my-uv-envs/avird-2026-app/.venv/Scripts/python.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return sys.executable


def default_spawn(cmd: list[str], cwd: Path, env: dict[str, str], log_path: Path) -> int:
    """Spawn a detached child whose output goes to a log file; return its PID."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "ab")  # noqa: SIM115 — handle outlives this call deliberately
    kwargs: dict = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:  # pragma: no cover - posix fallback
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, **kwargs)
    return proc.pid


def default_kill_tree(pid: int) -> bool:
    """Terminate a process tree. Returns True if something was killed."""
    if os.name == "nt":
        proc = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, check=False
        )
        return proc.returncode == 0
    try:  # pragma: no cover - posix fallback
        os.killpg(os.getpgid(pid), 15)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


# --- subcommands ----------------------------------------------------------------


def cmd_up(
    repo_root: Path = REPO_ROOT,
    timeout: float = 120.0,
    http_get=default_http_get,
    spawn=default_spawn,
    sleep=time.sleep,
) -> int:
    results, all_ok = service_status(http_get)
    if all_ok:
        print("[ok] stack already running — nothing spawned")
        for r in results:
            print(r.line())
        return 0

    api_env = parse_env_file(repo_root / "apps" / "api" / ".env")
    web_env = parse_env_file(repo_root / "apps" / "web" / ".env")
    logs_dir = repo_root / VERIFY_DIR / "logs"
    pids = load_pids(repo_root)
    api_ok, web_ok = results[0].ok, results[1].ok

    if not api_ok:
        env = merge_env(dict(os.environ), api_env)
        pids["api"] = spawn(
            [api_python(), "-m", "uvicorn", "app.main:app", "--reload", "--port", str(API_PORT)],
            repo_root / "apps" / "api",
            env,
            logs_dir / "api.log",
        )
        print(f"[ok] spawned api (pid {pids['api']}) — log: {logs_dir / 'api.log'}")

    if not web_ok:
        env = merge_env(dict(os.environ), web_env)
        # 127.0.0.1, not localhost: Node fetch tries ::1 first on Windows and
        # uvicorn binds IPv4 only — localhost ECONNREFUSEDs server-side.
        env.setdefault("API_URL", f"http://127.0.0.1:{API_PORT}")
        npm = "npm.cmd" if os.name == "nt" else "npm"
        pids["web"] = spawn(
            [npm, "run", "dev"],
            repo_root / "apps" / "web",
            env,
            logs_dir / "web.log",
        )
        print(f"[ok] spawned web (pid {pids['web']}) — log: {logs_dir / 'web.log'}")

    save_pids(repo_root, pids)

    if not api_ok and not wait_healthy(API_HEALTH_URL, timeout, http_get, sleep):
        print(
            f"[fail] api :{API_PORT} not healthy after {timeout:.0f}s — see {logs_dir / 'api.log'}"
        )
        return 1
    if not web_ok and not wait_healthy(WEB_URL, timeout, http_get, sleep):
        print(
            f"[fail] web :{WEB_PORT} not healthy after {timeout:.0f}s — see {logs_dir / 'web.log'}"
        )
        return 1

    results, all_ok = service_status(http_get)
    for r in results:
        print(r.line())
    return 0 if all_ok else 1


def cmd_status(http_get=default_http_get) -> int:
    results, all_ok = service_status(http_get)
    for r in results:
        print(r.line())
    return 0 if all_ok else 1


def cmd_down(repo_root: Path = REPO_ROOT, kill_tree=default_kill_tree) -> int:
    pids = load_pids(repo_root)
    if not pids:
        print("[ok] no recorded pids — nothing to stop")
        return 0
    for name, pid in pids.items():
        killed = kill_tree(pid)
        state = "stopped" if killed else "already gone"
        print(f"[ok] {name} (pid {pid}): {state}")
    save_pids(repo_root, {})
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_up = sub.add_parser("up", help="bring api + web up (no-op for healthy services)")
    p_up.add_argument(
        "--timeout", type=float, default=120.0, help="seconds to wait per service (default 120)"
    )
    sub.add_parser("status", help="health of both services + db state")
    sub.add_parser("down", help="stop recorded processes, clear pidfile")
    args = parser.parse_args(argv)

    if args.cmd == "up":
        return cmd_up(timeout=args.timeout)
    if args.cmd == "status":
        return cmd_status()
    return cmd_down()


if __name__ == "__main__":
    sys.exit(main())
