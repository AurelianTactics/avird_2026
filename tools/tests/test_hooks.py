"""Tests for the two thin enforcement hooks (.claude/hooks/).

Only wrapper logic is tested here — payload parsing, path filtering, the
stop_hook_active loop guard, and the block-decision shape. The gate rules
themselves are verify_evidence's tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "hooks"))

import mark_web_pending  # noqa: E402
import verify_evidence as ve  # noqa: E402
import verify_gate  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    for rel in ["apps/web/app/page.tsx", "apps/web/app/about/page.tsx"]:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"content of {rel}", encoding="utf-8")
    return tmp_path


def edit_payload(file_path):
    return {
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path},
    }


class TestMarkWebPending:
    def test_page_file_is_marked_pending(self, repo):
        rc = mark_web_pending.process(edit_payload("apps/web/app/page.tsx"), repo)
        assert rc == 0
        assert ve.load_pending(repo) == ["apps/web/app/page.tsx"]

    def test_docs_file_is_a_noop(self, repo):
        rc = mark_web_pending.process(edit_payload("docs/foo.md"), repo)
        assert rc == 0
        assert ve.load_pending(repo) == []

    def test_payload_without_file_path_is_a_noop(self, repo):
        assert mark_web_pending.process({}, repo) == 0
        assert mark_web_pending.process({"tool_input": {}}, repo) == 0
        assert ve.load_pending(repo) == []

    def test_empty_stdin_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / ".claude" / "hooks" / "mark_web_pending.py")],
            input="",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0

    def test_malformed_stdin_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / ".claude" / "hooks" / "mark_web_pending.py")],
            input="not json {",
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0


class TestVerifyGate:
    def test_stop_hook_active_allows_immediately(self, repo):
        ve.pending_add("apps/web/app/page.tsx", repo)  # debt that would block
        code, decision = verify_gate.process({"stop_hook_active": True}, repo)
        assert code == 0
        assert decision is None
        # debt untouched — nothing was checked or cleared
        assert ve.load_pending(repo) == ["apps/web/app/page.tsx"]

    def test_check_fail_emits_block_decision_with_verify_local(self, repo):
        ve.pending_add("apps/web/app/page.tsx", repo)
        code, decision = verify_gate.process({"stop_hook_active": False}, repo)
        assert code == 0
        assert decision["decision"] == "block"
        assert "/verify-local /" in decision["reason"]

    def test_check_pass_allows_and_clears_pending(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        shot = repo / ".verify" / "screenshots" / "about.png"
        shot.parent.mkdir(parents=True, exist_ok=True)
        shot.write_bytes(b"\x89PNG fake")
        ve.record_evidence("/about", str(shot), 0, "pass", repo)
        code, decision = verify_gate.process({"stop_hook_active": False}, repo)
        assert code == 0
        assert decision is None
        assert ve.load_pending(repo) == []

    def test_no_pending_allows(self, repo):
        code, decision = verify_gate.process({}, repo)
        assert code == 0
        assert decision is None

    def test_empty_stdin_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, str(REPO_ROOT / ".claude" / "hooks" / "verify_gate.py")],
            input="",
            capture_output=True,
            text=True,
        )
        # empty payload in the real repo: outcome depends on real pending
        # debt, but the wrapper must never crash
        assert proc.returncode == 0

    def test_block_output_is_valid_json_on_stdout(self, repo, capsys, monkeypatch):
        ve.pending_add("apps/web/app/page.tsx", repo)
        monkeypatch.setattr(verify_gate, "REPO_ROOT", repo)
        monkeypatch.setattr(verify_gate, "_read_payload", lambda: {"stop_hook_active": False})
        assert verify_gate.main() == 0
        out = capsys.readouterr().out
        decision = json.loads(out)
        assert decision["decision"] == "block"
