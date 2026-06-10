"""Tests for dev_stack's pure logic — env parsing, health polling, the
already-running guard, and stale-pidfile cleanup. No real servers or
processes: HTTP and spawn/kill are injected fakes."""

from __future__ import annotations

import dev_stack as ds


def http_up(url, timeout=5.0):
    if "health" in url:
        return 200, '{"status": "ok", "db": "ok"}'
    return 200, "<html>ok</html>"


def http_down(url, timeout=5.0):
    return 0, "ConnectError: refused"


# --- env-file parser ---------------------------------------------------------


class TestParseEnvFile:
    def test_parses_key_value_pairs(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("DATABASE_URL=postgresql://x\nPORT=8000\n", encoding="utf-8")
        assert ds.parse_env_file(f) == {"DATABASE_URL": "postgresql://x", "PORT": "8000"}

    def test_ignores_comments_and_blank_lines(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("# comment\n\nKEY=value\n   \n# another\n", encoding="utf-8")
        assert ds.parse_env_file(f) == {"KEY": "value"}

    def test_strips_surrounding_quotes(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("A=\"quoted\"\nB='single'\n", encoding="utf-8")
        assert ds.parse_env_file(f) == {"A": "quoted", "B": "single"}

    def test_missing_file_is_empty(self, tmp_path):
        assert ds.parse_env_file(tmp_path / "nope.env") == {}

    def test_merge_does_not_override_set_environ_key(self):
        merged = ds.merge_env(
            {"DATABASE_URL": "from-environ"}, {"DATABASE_URL": "from-file", "NEW": "x"}
        )
        assert merged["DATABASE_URL"] == "from-environ"
        assert merged["NEW"] == "x"


# --- health polling -----------------------------------------------------------


class TestWaitHealthy:
    def test_returns_ok_on_200(self):
        assert ds.wait_healthy("http://x/health", timeout=1, http_get=http_up, sleep=lambda s: None)

    def test_fails_after_timeout(self):
        clock = iter(range(100))
        assert not ds.wait_healthy(
            "http://x/health",
            timeout=3,
            http_get=http_down,
            sleep=lambda s: None,
            monotonic=lambda: next(clock),
        )


# --- status -------------------------------------------------------------------


class TestStatus:
    def test_ok_lines_include_db_state(self, capsys):
        assert ds.cmd_status(http_get=http_up) == 0
        out = capsys.readouterr().out
        assert "[ok] api :8000: db: ok" in out
        assert "[ok] web :3000" in out

    def test_nonzero_exit_and_fail_line_when_down(self, capsys):
        assert ds.cmd_status(http_get=http_down) == 1
        out = capsys.readouterr().out
        assert out.count("[fail]") == 2

    def test_api_up_db_down_is_visible_but_healthy(self, capsys):
        def http_db_down(url, timeout=5.0):
            if "health" in url:
                return 200, '{"status": "ok", "db": "down"}'
            return 200, "<html>ok</html>"

        assert ds.cmd_status(http_get=http_db_down) == 0
        assert "db: down" in capsys.readouterr().out


# --- up -----------------------------------------------------------------------


class TestUp:
    def test_already_running_spawns_nothing(self, tmp_path, capsys):
        ds.save_pids(tmp_path, {"api": 111, "web": 222})
        spawned = []
        rc = ds.cmd_up(
            repo_root=tmp_path,
            http_get=http_up,
            spawn=lambda *a, **k: spawned.append(a) or 999,
            sleep=lambda s: None,
        )
        assert rc == 0
        assert spawned == []
        assert "already running" in capsys.readouterr().out
        assert ds.load_pids(tmp_path) == {"api": 111, "web": 222}

    def test_cold_start_spawns_both_and_records_pids(self, tmp_path, capsys):
        calls = iter([1001, 1002])
        spawned = []

        # down until spawned, then up
        def http_get(url, timeout=5.0):
            return http_up(url) if spawned else http_down(url)

        def spawn(cmd, cwd, env, log_path):
            spawned.append(cmd)
            return next(calls)

        rc = ds.cmd_up(repo_root=tmp_path, http_get=http_get, spawn=spawn, sleep=lambda s: None)
        assert rc == 0
        assert len(spawned) == 2
        assert ds.load_pids(tmp_path) == {"api": 1001, "web": 1002}

    def test_spawns_only_the_dead_service(self, tmp_path):
        spawned = []

        def http_api_only(url, timeout=5.0):
            if "health" in url:
                return 200, '{"status": "ok", "db": "ok"}'
            return (200, "<html>ok</html>") if spawned else (0, "refused")

        def spawn(cmd, cwd, env, log_path):
            spawned.append(cmd)
            return 2001

        rc = ds.cmd_up(
            repo_root=tmp_path, http_get=http_api_only, spawn=spawn, sleep=lambda s: None
        )
        assert rc == 0
        assert len(spawned) == 1
        assert spawned[0][0].startswith("npm")  # only web was spawned
        assert ds.load_pids(tmp_path) == {"web": 2001}


# --- down ---------------------------------------------------------------------


class TestDown:
    def test_stale_pidfile_cleans_up_without_raising(self, tmp_path, capsys):
        ds.save_pids(tmp_path, {"api": 99999, "web": 99998})
        rc = ds.cmd_down(repo_root=tmp_path, kill_tree=lambda pid: False)
        assert rc == 0
        assert ds.load_pids(tmp_path) == {}
        assert "already gone" in capsys.readouterr().out

    def test_kills_recorded_pids_and_clears(self, tmp_path, capsys):
        ds.save_pids(tmp_path, {"api": 11, "web": 22})
        killed = []
        rc = ds.cmd_down(repo_root=tmp_path, kill_tree=lambda pid: killed.append(pid) or True)
        assert rc == 0
        assert sorted(killed) == [11, 22]
        assert ds.load_pids(tmp_path) == {}

    def test_no_pidfile_is_a_noop(self, tmp_path, capsys):
        rc = ds.cmd_down(repo_root=tmp_path, kill_tree=lambda pid: True)
        assert rc == 0
        assert "nothing to stop" in capsys.readouterr().out
