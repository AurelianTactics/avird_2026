"""Stop hook: block end-of-turn while web changes lack fresh passing evidence.

The deterministic half of "done means observed working": every page-affecting
Edit/Write was marked pending by mark_web_pending.py; this gate refuses to
let the turn end until each pending route has evidence that exists, passed,
references a real screenshot, and matches current content hashes
(tools/verify_evidence.check — all gate rules live there, not here).

Contract (confirmed against the hooks docs at build time):
  - input payload carries ``stop_hook_active``; when true this stop was
    already triggered by a stop hook — allow immediately to avoid loops
    (Claude Code also caps consecutive blocks at 8).
  - to block, emit JSON {"decision": "block", "reason": ...} on stdout; the
    reason names the exact /verify-local commands to run.

Failure posture: fail CLOSED on missing/stale evidence (that is the block),
fail OPEN on unexpected infrastructure errors — a broken gate must not brick
every session; it logs loudly to stderr instead.
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


def process(payload: dict, repo_root: Path = REPO_ROOT) -> tuple[int, dict | None]:
    """Return (exit_code, block_decision_or_None)."""
    if payload.get("stop_hook_active"):
        return 0, None  # this stop came from a stop hook — never loop

    results, ok = verify_evidence.check(repo_root, clear_satisfied=True)
    if ok:
        return 0, None

    reason = verify_evidence.block_message(results)
    return 0, {"decision": "block", "reason": reason}


def main() -> int:
    code, decision = process(_read_payload(), REPO_ROOT)
    if decision is not None:
        print(json.dumps(decision))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"verify-gate: unexpected error (failing open): {exc}", file=sys.stderr)
        sys.exit(0)  # infrastructure failure must not brick the session
