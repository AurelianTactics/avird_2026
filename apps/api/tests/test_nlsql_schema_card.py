"""Tests for the schema-card + value-grounding builder (plan P1, U2).

The DB is a fake connection returning a known column set and canned distinct
values — no Postgres. The card's job is to (a) classify raw-quoted vs clean
snake_case correctly, (b) render each identifier the way SQL needs it, and
(c) surface real value samples, so the downstream prompt can't drift.
"""

from __future__ import annotations

from app.nlsql import schema_card as sc

COLUMNS = [
    {"column_name": "master_entity", "data_type": "text"},
    {"column_name": "incident_date", "data_type": "date"},
    {"column_name": "State Clean", "data_type": "text"},
    {"column_name": "Highest Injury Severity Alleged", "data_type": "text"},
]

DISTINCT = {
    "master_entity": ["Cruise", "Waymo"],
    "State Clean": ["AZ", "CA"],
    "Highest Injury Severity Alleged": ["Fatality", "Minor", "No Injuries"],
}


class FakeConn:
    """Routes information_schema vs SELECT DISTINCT, like asyncpg's .fetch."""

    def __init__(self, columns=COLUMNS, distinct=DISTINCT, *, empty_table=False):
        self._columns = columns
        self._distinct = distinct
        self._empty_table = empty_table
        self.queries: list[str] = []

    async def fetch(self, query, *args):
        self.queries.append(query)
        if "information_schema" in query:
            return list(self._columns)
        if self._empty_table:
            return []
        # A value-sample query: figure out which column it asked for.
        for name, values in self._distinct.items():
            if sc.quote_identifier(name) in query:
                return [{"value": v} for v in values]
        return []


# --- classification + quoting (pure) ----------------------------------------


class TestQuoting:
    def test_clean_snake_case_is_bare(self):
        assert not sc.is_raw_column("master_entity")
        assert sc.quote_identifier("master_entity") == "master_entity"

    def test_mixed_case_with_spaces_is_quoted(self):
        assert sc.is_raw_column("Highest Injury Severity Alleged")
        assert (
            sc.quote_identifier("Highest Injury Severity Alleged")
            == '"Highest Injury Severity Alleged"'
        )

    def test_embedded_quote_is_doubled(self):
        assert sc.quote_identifier('weird"col') == '"weird""col"'


# --- build_schema_card ------------------------------------------------------


class TestBuildSchemaCard:
    async def test_lists_every_column_with_type(self):
        card = await sc.build_schema_card(FakeConn())
        names = {c.name for c in card.columns}
        assert names == {c["column_name"] for c in COLUMNS}
        by_name = {c.name: c for c in card.columns}
        assert by_name["incident_date"].data_type == "date"

    async def test_allowed_columns_matches_catalog(self):
        card = await sc.build_schema_card(FakeConn())
        assert card.allowed_columns == frozenset(c["column_name"] for c in COLUMNS)

    async def test_raw_vs_clean_rendered_correctly_in_card(self):
        card = await sc.build_schema_card(FakeConn())
        text = card.render()
        # raw column quoted, clean column bare
        assert '"Highest Injury Severity Alleged"' in text
        assert "master_entity — text (clean snake_case)" in text

    async def test_value_samples_pulled_for_low_cardinality_columns(self):
        card = await sc.build_schema_card(FakeConn())
        assert card.value_samples["master_entity"] == ["Cruise", "Waymo"]
        assert card.value_samples["State Clean"] == ["AZ", "CA"]
        assert "Fatality" in card.value_samples["Highest Injury Severity Alleged"]

    async def test_card_contains_canonical_vs_raw_note_and_samples(self):
        # The U2 verification: the card spells out the trap and grounds values.
        card = await sc.build_schema_card(FakeConn())
        text = card.render()
        assert "Column-naming trap" in text
        assert "Known values" in text
        assert "Waymo" in text and "AZ" in text and "Fatality" in text

    async def test_empty_table_yields_empty_samples_without_error(self):
        card = await sc.build_schema_card(FakeConn(empty_table=True))
        assert card.value_samples["master_entity"] == []
        # Still renders.
        assert "Table: treated_incident_reports" in card.render()

    async def test_missing_value_column_is_skipped_not_raised(self):
        # A schema lacking one of the curated value columns must not blow up.
        columns = [{"column_name": "master_entity", "data_type": "text"}]
        card = await sc.build_schema_card(FakeConn(columns=columns))
        assert "master_entity" in card.value_samples
        assert "State Clean" not in card.value_samples

    async def test_distinct_query_quotes_raw_value_columns(self):
        conn = FakeConn()
        await sc.build_schema_card(conn)
        joined = "\n".join(conn.queries)
        # The raw value column is quoted in its SELECT DISTINCT.
        assert 'SELECT DISTINCT "State Clean"' in joined
        # The clean one is not.
        assert "SELECT DISTINCT master_entity" in joined
