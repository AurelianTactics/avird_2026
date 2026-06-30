"""Tests for the SQL validator (plan P1, U3).

The security scenarios are the point: every injection vector must come back
``ok=False`` with a readable reason, and the EXPLAIN path must return zero rows.
The static gate is DB-free; the EXPLAIN test uses a fake connection.
"""

from __future__ import annotations

import pytest

from app.nlsql import validate as v

# --- happy path + LIMIT injection -------------------------------------------


class TestHappyPath:
    def test_well_formed_select_passes(self):
        res = v.validate_static(
            "SELECT master_entity FROM treated_incident_reports WHERE master_entity = 'Waymo'"
        )
        assert res.ok
        assert res.normalized_sql is not None

    def test_missing_limit_gets_default_cap_injected(self):
        res = v.validate_static("SELECT * FROM treated_incident_reports")
        assert res.ok
        assert f"LIMIT {v.DEFAULT_LIMIT}" in res.normalized_sql

    def test_existing_limit_is_left_unchanged(self):
        res = v.validate_static("SELECT * FROM treated_incident_reports LIMIT 10")
        assert res.ok
        assert "LIMIT 10" in res.normalized_sql
        assert str(v.DEFAULT_LIMIT) not in res.normalized_sql

    def test_quoted_raw_column_is_preserved(self):
        res = v.validate_static(
            'SELECT "Highest Injury Severity Alleged" FROM treated_incident_reports'
        )
        assert res.ok
        assert '"Highest Injury Severity Alleged"' in res.normalized_sql

    def test_union_of_allowed_tables_passes(self):
        res = v.validate_static(
            "SELECT master_entity FROM treated_incident_reports "
            "UNION SELECT master_entity FROM treated_incident_reports"
        )
        assert res.ok

    def test_cte_over_allowed_table_passes(self):
        res = v.validate_static(
            "WITH x AS (SELECT master_entity FROM treated_incident_reports) SELECT * FROM x"
        )
        assert res.ok


# --- security: statement-type + injection -----------------------------------


class TestSecurity:
    def test_multi_statement_drop_rejected(self):
        res = v.validate_static("SELECT 1; DROP TABLE treated_incident_reports")
        assert not res.ok
        assert "single statement" in res.reason

    def test_cte_wrapped_dml_rejected(self):
        res = v.validate_static(
            "WITH x AS (DELETE FROM treated_incident_reports RETURNING *) SELECT * FROM x"
        )
        assert not res.ok
        assert "read-only" in res.reason

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO treated_incident_reports VALUES (1)",
            "UPDATE treated_incident_reports SET master_entity = 'x'",
            "DELETE FROM treated_incident_reports",
            "DROP TABLE treated_incident_reports",
            "SELECT * INTO foo FROM treated_incident_reports",
            "VACUUM",
        ],
    )
    def test_dml_ddl_and_commands_rejected(self, sql):
        res = v.validate_static(sql)
        assert not res.ok

    def test_unlisted_table_rejected(self):
        res = v.validate_static("SELECT * FROM derived_spend")
        assert not res.ok
        assert "allow-list" in res.reason

    def test_pg_catalog_table_rejected(self):
        res = v.validate_static("SELECT * FROM pg_user")
        assert not res.ok
        assert "not allowed" in res.reason

    def test_information_schema_rejected(self):
        res = v.validate_static("SELECT * FROM information_schema.tables")
        assert not res.ok
        assert "not allowed" in res.reason

    def test_garbage_is_rejected_not_raised(self):
        res = v.validate_static("this is not sql at all <<<")
        assert not res.ok

    def test_empty_is_rejected(self):
        assert not v.validate_static("   ").ok


# --- EXPLAIN dry-run --------------------------------------------------------


class FakeExplainConn:
    """Records EXPLAIN calls; optionally raises to simulate a bad column."""

    def __init__(self, *, raise_on=None):
        self._raise_on = raise_on
        self.executed: list[str] = []
        self.fetched = 0

    async def execute(self, query, *args):
        self.executed.append(query)
        if self._raise_on and self._raise_on in query:
            raise RuntimeError('UndefinedColumnError: column "nope" does not exist')
        return "EXPLAIN"

    async def fetch(self, query, *args):  # pragma: no cover - must never be called
        self.fetched += 1
        return []


class TestExplain:
    async def test_valid_sql_explains_and_passes(self):
        conn = FakeExplainConn()
        res = await v.validate_sql("SELECT master_entity FROM treated_incident_reports", conn=conn)
        assert res.ok
        # EXPLAIN ran, and it used execute (no row-returning fetch).
        assert any(q.startswith("EXPLAIN ") for q in conn.executed)
        assert conn.fetched == 0

    async def test_column_typo_fails_at_explain_with_reason(self):
        conn = FakeExplainConn(raise_on="nope")
        res = await v.validate_sql("SELECT nope FROM treated_incident_reports", conn=conn)
        assert not res.ok
        assert "EXPLAIN failed" in res.reason
        assert conn.fetched == 0

    async def test_static_rejection_skips_explain(self):
        conn = FakeExplainConn()
        res = await v.validate_sql("DROP TABLE treated_incident_reports", conn=conn)
        assert not res.ok
        # A structurally-rejected candidate never reaches the DB.
        assert conn.executed == []

    async def test_no_conn_runs_static_only(self):
        res = await v.validate_sql("SELECT * FROM treated_incident_reports", conn=None)
        assert res.ok
