"""PostToolUse hook: mark page-affecting web edits as pending verification.

Reads the Claude Code hook payload from stdin, extracts the touched file
path, and delegates to tools/verify_evidence.pending_add (in-process import,
not a subprocess — this runs on every Edit/Write and must stay milliseconds).
pending_add itself is the only filter: non-page-affecting paths are a no-op.

Silent on success, never blocks the edit, fails open on infrastructure
errors — the same posture as format_on_edit.py. The Stop-hook gate
(verify_gate.py) is what enforces; this hook only bookkeeps.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import verify_evidence  # noqa: E402


def _read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def process(payload: dict, repo_root: Path = REPO_ROOT) -> int:
    tool_input = payload.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("path")
    if not file_path:
        return 0
    verify_evidence.pending_add(file_path, repo_root)
    return 0


def main() -> int:
    return process(_read_payload(), REPO_ROOT)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"pending-hook: unexpected error: {exc}", file=sys.stderr)
        sys.exit(0)  # never block the edit
