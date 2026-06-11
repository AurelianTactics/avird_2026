"""Tests for verify_evidence — the deterministic gate logic.

Each test builds a throwaway repo tree under tmp_path mirroring the real
apps/web/app layout, so mapping, pending, and freshness rules are exercised
without touching the actual repo or any git state.
"""

from __future__ import annotations

import json

import pytest

import verify_evidence as ve

ALL_ROUTES = ["/", "/about", "/groupings", "/incidents/[reportId]"]

PAGE_FILES = [
    "apps/web/app/page.tsx",
    "apps/web/app/about/page.tsx",
    "apps/web/app/groupings/page.tsx",
    "apps/web/app/incidents/[reportId]/page.tsx",
]
SHARED_FILES = [
    "apps/web/app/layout.tsx",
    "apps/web/app/globals.css",
    "apps/web/app/components/Nav.tsx",
    "apps/web/app/lib/api.ts",
]
TEST_FILES = [
    "apps/web/app/page.test.tsx",
    "apps/web/app/components/Nav.test.tsx",
]


@pytest.fixture
def repo(tmp_path):
    for rel in PAGE_FILES + SHARED_FILES + TEST_FILES:
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"content of {rel}", encoding="utf-8")
    api = tmp_path / "apps/api/app/main.py"
    api.parent.mkdir(parents=True, exist_ok=True)
    api.write_text("print('api')", encoding="utf-8")
    return tmp_path


def make_screenshot(repo, route):
    p = repo / ".verify" / "screenshots" / (ve._evidence_name(route) + ".png")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"\x89PNG fake")
    return p


def record_pass(repo, route, **kwargs):
    return ve.record_evidence(
        route,
        str(make_screenshot(repo, route)),
        kwargs.pop("console_errors", 0),
        kwargs.pop("result", "pass"),
        repo,
        **kwargs,
    )


# --- mapping -------------------------------------------------------------


class TestMapping:
    def test_route_inventory_globs_all_pages(self, repo):
        assert sorted(ve.route_inventory(repo)) == ALL_ROUTES

    def test_root_page_maps_to_root_route(self, repo):
        assert ve.affected_routes("apps/web/app/page.tsx", repo) == ["/"]

    def test_segment_page_maps_to_segment_route(self, repo):
        assert ve.affected_routes("apps/web/app/groupings/page.tsx", repo) == ["/groupings"]

    def test_dynamic_page_maps_to_template_route(self, repo):
        assert ve.affected_routes("apps/web/app/incidents/[reportId]/page.tsx", repo) == [
            "/incidents/[reportId]"
        ]

    @pytest.mark.parametrize(
        "shared",
        [
            "apps/web/app/layout.tsx",
            "apps/web/app/components/Nav.tsx",
            "apps/web/app/lib/api.ts",
            "apps/web/app/globals.css",
        ],
    )
    def test_shared_files_affect_all_routes(self, repo, shared):
        assert ve.affected_routes(shared, repo) == ALL_ROUTES

    @pytest.mark.parametrize(
        "non_affecting",
        [
            "apps/web/app/page.test.tsx",
            "apps/web/app/components/Nav.test.tsx",
            "apps/api/app/main.py",
            "docs/plans/some-plan.md",
        ],
    )
    def test_non_affecting_files_map_to_no_routes(self, repo, non_affecting):
        assert ve.affected_routes(non_affecting, repo) == []

    def test_absolute_path_inside_repo_is_normalized(self, repo):
        absolute = repo / "apps" / "web" / "app" / "about" / "page.tsx"
        assert ve.affected_routes(absolute, repo) == ["/about"]

    def test_absolute_path_outside_repo_maps_to_no_routes(self, repo, tmp_path_factory):
        outside = tmp_path_factory.mktemp("elsewhere") / "page.tsx"
        outside.write_text("x")
        assert ve.affected_routes(outside, repo) == []


# --- pending bookkeeping ---------------------------------------------------


class TestPending:
    def test_add_is_idempotent(self, repo):
        ve.pending_add("apps/web/app/page.tsx", repo)
        ve.pending_add("apps/web/app/page.tsx", repo)
        assert ve.load_pending(repo) == ["apps/web/app/page.tsx"]

    def test_non_affecting_file_is_a_noop(self, repo):
        assert ve.pending_add("docs/notes.md", repo) is False
        assert ve.load_pending(repo) == []
        assert not (repo / ".verify" / "pending.json").exists()

    def test_pending_routes_unions_across_files(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        ve.pending_add("apps/web/app/groupings/page.tsx", repo)
        assert ve.pending_routes(repo) == ["/about", "/groupings"]

    def test_shared_pending_file_wants_all_routes(self, repo):
        ve.pending_add("apps/web/app/layout.tsx", repo)
        assert ve.pending_routes(repo) == ALL_ROUTES

    def test_pending_persists_across_invocations(self, repo):
        ve.pending_add("apps/web/app/page.tsx", repo)
        # fresh read from disk — nothing resets implicitly
        assert ve.load_pending(repo) == ["apps/web/app/page.tsx"]
        assert ve.pending_routes(repo) == ["/"]

    def test_pending_clear_empties_explicitly(self, repo):
        ve.pending_add("apps/web/app/page.tsx", repo)
        ve.save_pending(repo, [])
        assert ve.load_pending(repo) == []


# --- record / check ---------------------------------------------------------


class TestRecordCheck:
    def test_happy_path_passes_and_clear_satisfied_empties_pending(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        record_pass(repo, "/about")
        results, ok = ve.check(repo, clear_satisfied=True)
        assert ok
        assert [r.route for r in results] == ["/about"]
        assert all(r.ok for r in results)
        assert ve.load_pending(repo) == []

    def test_empty_pending_passes_silently(self, repo):
        results, ok = ve.check(repo)
        assert ok
        assert results == []

    def test_modifying_affecting_file_blocks_that_route_only(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        ve.pending_add("apps/web/app/groupings/page.tsx", repo)
        record_pass(repo, "/about")
        record_pass(repo, "/groupings")
        (repo / "apps/web/app/groupings/page.tsx").write_text("changed", encoding="utf-8")
        results, ok = ve.check(repo)
        assert not ok
        by_route = {r.route: r for r in results}
        assert by_route["/about"].ok
        assert not by_route["/groupings"].ok
        assert "apps/web/app/groupings/page.tsx" in by_route["/groupings"].detail

    def test_editing_shared_file_stales_all_routes(self, repo):
        ve.pending_add("apps/web/app/layout.tsx", repo)
        for route in ALL_ROUTES:
            record_pass(repo, route)
        results, ok = ve.check(repo)
        assert ok
        (repo / "apps/web/app/layout.tsx").write_text("changed", encoding="utf-8")
        results, ok = ve.check(repo)
        assert not ok
        assert all(not r.ok for r in results)
        assert len(results) == len(ALL_ROUTES)

    def test_fail_result_blocks(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        record_pass(repo, "/about", result="fail", console_errors=3)
        results, ok = ve.check(repo)
        assert not ok
        assert "fail" in results[0].detail

    def test_missing_screenshot_blocks(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        shot = make_screenshot(repo, "/about")
        ve.record_evidence("/about", str(shot), 0, "pass", repo)
        shot.unlink()
        results, ok = ve.check(repo)
        assert not ok
        assert "screenshot" in results[0].detail

    def test_missing_evidence_blocks(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        results, ok = ve.check(repo)
        assert not ok
        assert "no evidence" in results[0].detail

    def test_record_refuses_nonexistent_screenshot(self, repo):
        with pytest.raises(FileNotFoundError):
            ve.record_evidence("/about", str(repo / "nope.png"), 0, "pass", repo)

    def test_deleted_page_drops_its_debt(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        (repo / "apps/web/app/about/page.tsx").unlink()
        (repo / "apps/web/app/about").rmdir()
        results, ok = ve.check(repo, clear_satisfied=True)
        assert ok
        assert ve.load_pending(repo) == []

    def test_clear_satisfied_keeps_blocked_entries(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        ve.pending_add("apps/web/app/groupings/page.tsx", repo)
        record_pass(repo, "/about")
        results, ok = ve.check(repo, clear_satisfied=True)
        assert not ok
        assert ve.load_pending(repo) == ["apps/web/app/groupings/page.tsx"]

    def test_evidence_records_sample_url_for_dynamic_route(self, repo):
        out = record_pass(
            repo,
            "/incidents/[reportId]",
            sample_url="http://localhost:3000/incidents/RPT-0001",
        )
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["sample_url"] == "http://localhost:3000/incidents/RPT-0001"
        assert data["route"] == "/incidents/[reportId]"


# --- block message -----------------------------------------------------------


class TestBlockMessage:
    def test_block_message_names_exact_verify_local_commands(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        ve.pending_add("apps/web/app/groupings/page.tsx", repo)
        results, ok = ve.check(repo)
        assert not ok
        msg = ve.block_message(results)
        assert "/verify-local /about" in msg
        assert "/verify-local /groupings" in msg

    def test_block_message_omits_passing_routes_from_commands(self, repo):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        ve.pending_add("apps/web/app/groupings/page.tsx", repo)
        record_pass(repo, "/about")
        results, ok = ve.check(repo)
        msg = ve.block_message(results)
        assert "/verify-local /groupings" in msg
        assert "/verify-local /about" not in msg


# --- CLI ----------------------------------------------------------------------


class TestCli:
    def test_routes_lists_inventory(self, repo, capsys):
        assert ve.main(["--repo-root", str(repo), "routes"]) == 0
        assert capsys.readouterr().out.split() == ALL_ROUTES

    def test_check_exit_codes(self, repo, capsys):
        assert ve.main(["--repo-root", str(repo), "check"]) == 0  # empty pending
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        assert ve.main(["--repo-root", str(repo), "check"]) == 1
        assert "/verify-local /about" in capsys.readouterr().out
        record_pass(repo, "/about")
        assert ve.main(["--repo-root", str(repo), "check", "--clear-satisfied"]) == 0
        assert ve.load_pending(repo) == []

    def test_record_cli_rejects_missing_screenshot(self, repo, capsys):
        rc = ve.main(
            [
                "--repo-root",
                str(repo),
                "record",
                "--route",
                "/about",
                "--screenshot",
                "nope.png",
                "--console-errors",
                "0",
                "--result",
                "pass",
            ]
        )
        assert rc == 2

    def test_record_cli_normalizes_slashless_route(self, repo, capsys):
        shot = make_screenshot(repo, "/about")
        rc = ve.main(
            [
                "--repo-root",
                str(repo),
                "record",
                "--route",
                "about",  # documented slash-less shape (Git Bash mangles "/about")
                "--screenshot",
                str(shot),
                "--console-errors",
                "0",
                "--result",
                "pass",
            ]
        )
        assert rc == 0
        assert ve.evidence_path("/about", repo).exists()

    def test_record_cli_dot_is_root_route_alias(self, repo):
        shot = make_screenshot(repo, "/")
        rc = ve.main(
            [
                "--repo-root",
                str(repo),
                "record",
                "--route",
                ".",
                "--screenshot",
                str(shot),
                "--console-errors",
                "0",
                "--result",
                "pass",
            ]
        )
        assert rc == 0
        assert ve.evidence_path("/", repo).exists()

    def test_record_cli_rejects_shell_mangled_route(self, repo, capsys):
        shot = make_screenshot(repo, "/about")
        rc = ve.main(
            [
                "--repo-root",
                str(repo),
                "record",
                "--route",
                "C:/Program Files/Git/about",  # MSYS path-conversion artifact
                "--screenshot",
                str(shot),
                "--console-errors",
                "0",
                "--result",
                "pass",
            ]
        )
        assert rc == 2
        assert "without the leading slash" in capsys.readouterr().err

    def test_pending_clear_cli(self, repo, capsys):
        ve.pending_add("apps/web/app/about/page.tsx", repo)
        assert ve.main(["--repo-root", str(repo), "pending-clear"]) == 0
        assert ve.load_pending(repo) == []
