"""Smoke tests for the kgquery CLI (plan P3, U15).

A thin wrapper over the U15 agent, so the tests just prove the pipe runs:
--help exits, and a fully-stubbed run (fake graph seam + canned-Cypher model,
no Neo4j, no key) prints a result and exits 0.
"""

from __future__ import annotations

import pytest

from app.kgquery import cli
from tests.test_kgquery_agent import FakeKgData


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "question" in capsys.readouterr().out.lower()


def test_stubbed_run_exits_zero(capsys):
    code = cli.main(
        ["which companies had the most incidents?"],
        data=FakeKgData(rows=[{"company": "Waymo", "incidents": 3}]),
        model=cli.StubCypherModel(),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "executed Cypher" in out
    assert "Waymo" in out


def test_verbose_prints_graph_card(capsys):
    code = cli.main(["q", "--verbose"], data=FakeKgData(), model=cli.StubCypherModel())
    assert code == 0
    assert "graph card" in capsys.readouterr().out.lower()


def test_graph_unreachable_prints_degrade_not_traceback(capsys):
    code = cli.main(["q"], data=FakeKgData(unreachable=True), model=cli.StubCypherModel())
    assert code == 0
    assert "GRAPH UNAVAILABLE" in capsys.readouterr().out


def test_missing_neo4j_env_prints_setup_hint(monkeypatch, capsys):
    for var in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    code = cli.main(["q"])  # no injected data -> real seam -> env hint
    assert code == 2
    assert "NEO4J_URI" in capsys.readouterr().err


def test_build_default_model_uses_stub_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(cli.build_default_model(), cli.StubCypherModel)
