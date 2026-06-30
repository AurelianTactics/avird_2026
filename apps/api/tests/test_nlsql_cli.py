"""Smoke tests for the nlsql CLI (plan P1, U5).

A thin wrapper over the U4 agent, so the tests just prove the pipe runs: --help
exits, and a fully-stubbed run (fake data + stub model, no DB, no key) prints a
result and exits 0.
"""

from __future__ import annotations

import pytest

from app.nlsql import cli
from app.nlsql import schema_card as sc
from app.nlsql import validate as v

CARD = sc.SchemaCard(
    table="treated_incident_reports",
    columns=[sc.ColumnInfo("master_entity", "text")],
    value_samples={"master_entity": ["Waymo"]},
)


class FakeData:
    async def schema_card(self):
        return CARD

    async def validate(self, sql):
        return v.validate_static(sql)

    async def execute(self, sql):
        return [{"master_entity": "Waymo", "n": 3}]


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "question" in capsys.readouterr().out.lower()


def test_stubbed_run_exits_zero(capsys):
    code = cli.main(
        ["which companies had the most fatal incidents?"],
        data=FakeData(),
        model=cli.StubSqlModel(),
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "executed SQL" in out
    assert "Waymo" in out


def test_verbose_prints_schema_card(capsys):
    code = cli.main(["q"], data=FakeData(), model=cli.StubSqlModel())
    assert code == 0
    code = cli.main(["q", "--verbose"], data=FakeData(), model=cli.StubSqlModel())
    assert code == 0
    assert "schema card" in capsys.readouterr().out.lower()


def test_build_default_model_uses_stub_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert isinstance(cli.build_default_model(), cli.StubSqlModel)
