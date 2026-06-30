"""Tests for setup_readonly_role's pure logic — URL parsing, the missing-env
hints, and the shape of the generated grant DDL. No real Postgres: the
create-role / permission-error scenarios are integration checks run by hand
against the seeded local DB (see the module docstring and stack.md)."""

from __future__ import annotations

import pytest

import setup_readonly_role as sr


# --- parse_readonly_url ------------------------------------------------------


class TestParseReadonlyUrl:
    def test_extracts_role_password_and_dbname(self):
        spec = sr.parse_readonly_url("postgresql://avird_readonly:s3cret@localhost:5432/avird_dev")
        assert spec.role == "avird_readonly"
        assert spec.password == "s3cret"
        assert spec.dbname == "avird_dev"

    def test_percent_decodes_credentials(self):
        # A password with URL-reserved chars arrives percent-encoded; the role is
        # created with the decoded value so a later connect with the same URL matches.
        spec = sr.parse_readonly_url(
            "postgresql://avird_readonly:p%40ss%2Fword@localhost:5432/avird_dev"
        )
        assert spec.password == "p@ss/word"

    def test_normalizes_sqlalchemy_and_bare_schemes(self):
        for url in (
            "postgres://ro:pw@localhost:5432/avird_dev",
            "postgresql+psycopg://ro:pw@localhost:5432/avird_dev",
        ):
            assert sr.parse_readonly_url(url).dbname == "avird_dev"

    def test_missing_password_raises(self):
        with pytest.raises(ValueError, match="password"):
            sr.parse_readonly_url("postgresql://avird_readonly@localhost:5432/avird_dev")

    def test_missing_dbname_raises(self):
        with pytest.raises(ValueError, match="database name"):
            sr.parse_readonly_url("postgresql://ro:pw@localhost:5432/")

    def test_missing_role_raises(self):
        with pytest.raises(ValueError, match="role"):
            sr.parse_readonly_url("postgresql://:pw@localhost:5432/avird_dev")


# --- grant_statements --------------------------------------------------------


class TestGrantStatements:
    def _rendered(self, spec):
        return [s.as_string(None) for s in sr.grant_statements(spec)]

    def test_grants_select_only_on_the_treated_table(self):
        spec = sr.RoleSpec(role="avird_readonly", password="pw", dbname="avird_dev")
        text = "\n".join(self._rendered(spec))
        assert 'GRANT SELECT ON "treated_incident_reports" TO "avird_readonly"' in text
        # No write or DDL privilege is ever granted.
        for forbidden in ("GRANT INSERT", "GRANT UPDATE", "GRANT DELETE", "GRANT ALL"):
            assert forbidden not in text

    def test_revokes_ambient_table_grants_before_granting(self):
        spec = sr.RoleSpec(role="avird_readonly", password="pw", dbname="avird_dev")
        rendered = self._rendered(spec)
        text = "\n".join(rendered)
        assert "REVOKE ALL ON ALL TABLES IN SCHEMA public" in text
        # The single SELECT grant comes after the blanket revoke (least privilege).
        revoke_idx = next(i for i, s in enumerate(rendered) if "REVOKE ALL ON ALL TABLES" in s)
        grant_idx = next(i for i, s in enumerate(rendered) if "GRANT SELECT" in s)
        assert revoke_idx < grant_idx

    def test_sets_role_level_guardrails(self):
        spec = sr.RoleSpec(role="avird_readonly", password="pw", dbname="avird_dev")
        text = "\n".join(self._rendered(spec))
        assert "statement_timeout" in text
        assert "work_mem" in text

    def test_role_and_db_are_quoted_identifiers(self):
        # A role name that needs quoting must be emitted as a quoted identifier,
        # never bare — the driver-side quoting is the injection control.
        spec = sr.RoleSpec(role="weird-role", password="pw", dbname="avird_dev")
        text = "\n".join(self._rendered(spec))
        assert '"weird-role"' in text


# --- _resolve_urls (the missing-env hints) -----------------------------------


class TestResolveUrls:
    def _args(self, database_url=None, readonly_database_url=None):
        import argparse

        return argparse.Namespace(
            database_url=database_url, readonly_database_url=readonly_database_url
        )

    def test_missing_admin_url_returns_none_with_hint(self, monkeypatch, capsys):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("READONLY_DATABASE_URL", "postgresql://ro:pw@localhost/avird_dev")
        assert sr._resolve_urls(self._args()) is None
        assert "DATABASE_URL is not set" in capsys.readouterr().err

    def test_missing_readonly_url_returns_none_with_hint(self, monkeypatch, capsys):
        monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:pw@localhost/avird_dev")
        monkeypatch.delenv("READONLY_DATABASE_URL", raising=False)
        assert sr._resolve_urls(self._args()) is None
        err = capsys.readouterr().err
        assert "READONLY_DATABASE_URL is not set" in err
        # The hint is a one-liner pointing at the fix, not a raw traceback.
        assert "Traceback" not in err

    def test_both_present_returns_pair(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:pw@localhost/avird_dev")
        monkeypatch.setenv("READONLY_DATABASE_URL", "postgresql://ro:pw@localhost/avird_dev")
        urls = sr._resolve_urls(self._args())
        assert urls is not None
        admin, readonly = urls
        assert "postgres:" in admin and "ro:" in readonly
