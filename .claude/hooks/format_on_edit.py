"""PostToolUse hook: format the file just edited.

Reads the Claude Code hook payload from stdin, extracts the touched
file path, and dispatches to ruff (Python) or prettier (TypeScript)
based on path glob. Silent on success; logs a one-line warning to
stderr if the formatter is missing or fails. Never blocks the edit.

Scoped narrowly:
  apps/api/**/*.py        -> ruff format
  apps/web/**/*.{ts,tsx}  -> prettier --write

Anything else is a no-op.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _resolve_target(payload: dict) -> Path | None:
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path:
        return None
    p = Path(file_path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p if p.exists() else None


def _matches(path: Path, root: Path, patterns: tuple[str, ...]) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    rel_str = rel.as_posix()
    return any(rel.match(pat) or rel_str.endswith(pat.lstrip("*")) for pat in patterns)


def _run(cmd: list[str], cwd: Path) -> None:
    exe = shutil.which(cmd[0])
    if not exe:
        print(f"format-hook: '{cmd[0]}' not found on PATH; skipping", file=sys.stderr)
        return
    try:
        subprocess.run([exe, *cmd[1:]], cwd=cwd, check=False, capture_output=True)
    except Exception as exc:  # noqa: BLE001
        print(f"format-hook: {cmd[0]} failed: {exc}", file=sys.stderr)


def main() -> int:
    payload = _read_payload()
    target = _resolve_target(payload)
    if target is None:
        return 0

    api_root = REPO_ROOT / "apps" / "api"
    web_root = REPO_ROOT / "apps" / "web"

    if _matches(target, api_root, ("*.py",)):
        _run(["ruff", "format", str(target)], cwd=REPO_ROOT)
        return 0

    if _matches(target, web_root, ("*.ts", "*.tsx")):
        rel = target.relative_to(web_root).as_posix()
        _run(["npx", "--no-install", "prettier", "--write", rel], cwd=web_root)
        return 0

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"format-hook: unexpected error: {exc}", file=sys.stderr)
        sys.exit(0)  # never block the edit
