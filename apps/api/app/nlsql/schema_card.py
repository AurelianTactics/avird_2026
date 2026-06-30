"""Schema-card + value-grounding builder (plan P1, U2).

The text-to-SQL model can only be as right as the context it's given. This
module generates that grounding **from the live DB** — the column catalog from
``information_schema`` and distinct-value samples for the low-cardinality
columns — so the prompt can never drift from the actual table the way a
hand-maintained schema description would. It generalizes
``IncidentData.fetch_known_values`` from "entity/state for the bounded filter"
to "the whole column catalog for open-ended SQL."

It also surfaces the **column-naming trap** that this dataset is full of: the
treated table mixes *raw passthrough* columns with mixed-case-and-spaces names
that must be double-quoted in SQL (``"Highest Injury Severity Alleged"``) with
*cleaned* snake_case columns that don't (``master_entity``, ``incident_date``).
A model that quotes the wrong one writes SQL that fails at ``EXPLAIN``; the card
spells the distinction out and renders each identifier the way SQL needs it.

The DB seam is a duck-typed async connection exposing ``.fetch(query, *args)``
(asyncpg's shape), so tests inject a fake and run without Postgres.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

TABLE = "treated_incident_reports"

# Low-cardinality columns worth grounding with their distinct values, so the
# model filters on real values (``master_entity = 'Waymo'``) instead of
# hallucinated ones. Mirrors the bounded filter's known-value vocabulary
# (``IncidentData.fetch_known_values``) plus severity. DB-name form: the raw
# columns carry their mixed-case spelling; the builder quotes them as needed.
VALUE_COLUMNS: tuple[str, ...] = (
    "master_entity",
    "State Clean",
    "Highest Injury Severity Alleged",
)

# Distinct values pulled per low-cardinality column. A cap so a column that
# turns out higher-cardinality than expected can't blow up the prompt.
VALUE_SAMPLE_LIMIT = 60

# A clean snake_case identifier needs no quoting; anything else (spaces,
# mixed case, punctuation) is a raw passthrough column and must be quoted.
_CLEAN_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]*$")


class Connection(Protocol):
    """The async DB seam: asyncpg's ``.fetch``. Tests pass a fake."""

    async def fetch(self, query: str, *args: Any) -> list[Any]: ...


def is_raw_column(name: str) -> bool:
    """True if ``name`` must be double-quoted in SQL (raw passthrough column)."""
    return _CLEAN_IDENTIFIER.match(name) is None


def quote_identifier(name: str) -> str:
    """Render a column name as a SQL identifier — quoted only when it has to be.

    Clean snake_case stays bare (``master_entity``); a raw mixed-case-with-spaces
    column is double-quoted with any internal quote doubled
    (``"Highest Injury Severity Alleged"``).
    """
    if is_raw_column(name):
        escaped = name.replace('"', '""')
        return f'"{escaped}"'
    return name


@dataclass(frozen=True)
class ColumnInfo:
    """One column's catalog entry."""

    name: str
    data_type: str

    @property
    def is_raw(self) -> bool:
        return is_raw_column(self.name)

    @property
    def identifier(self) -> str:
        return quote_identifier(self.name)


@dataclass(frozen=True)
class SchemaCard:
    """The grounding context: column catalog + value samples for the prompt.

    ``allowed_columns`` is the set of real column names — best-effort
    defense-in-depth the validator (U3) can consult, behind the read-only role
    and table allow-list which are the real boundary.
    """

    table: str
    columns: list[ColumnInfo]
    value_samples: dict[str, list[str]] = field(default_factory=dict)

    @property
    def allowed_columns(self) -> frozenset[str]:
        return frozenset(c.name for c in self.columns)

    def render(self) -> str:
        """A compact text card for the system prompt."""
        lines = [
            f"Table: {self.table}",
            "",
            "Column-naming trap — this table mixes two styles, and which one a "
            "column uses decides whether you must double-quote it:",
            "  - Cleaned snake_case columns are written bare: master_entity, incident_date.",
            "  - Raw passthrough columns have mixed case and spaces and MUST be "
            'double-quoted exactly: "Highest Injury Severity Alleged".',
            "",
            "Columns (identifier — type):",
        ]
        for col in self.columns:
            tag = "raw, quote it" if col.is_raw else "clean snake_case"
            lines.append(f"  - {col.identifier} — {col.data_type} ({tag})")
        if self.value_samples:
            lines.append("")
            lines.append("Known values for low-cardinality columns (filter on these):")
            for name, values in self.value_samples.items():
                shown = ", ".join(values) if values else "(none)"
                lines.append(f"  - {quote_identifier(name)}: {shown}")
        return "\n".join(lines)


async def _fetch_columns(conn: Connection, table: str) -> list[ColumnInfo]:
    rows = await conn.fetch(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = $1 ORDER BY ordinal_position",
        table,
    )
    return [ColumnInfo(name=r["column_name"], data_type=r["data_type"]) for r in rows]


async def _fetch_value_sample(conn: Connection, table: str, column: str, limit: int) -> list[str]:
    # The column identifier is one of our own VALUE_COLUMNS constants, rendered
    # through quote_identifier — never a caller/LLM-supplied string — so this
    # f-string can't carry injected SQL (same discipline as data.SORT_COLUMNS).
    ident = quote_identifier(column)
    rows = await conn.fetch(
        f"SELECT DISTINCT {ident} AS value FROM {table} "
        f"WHERE {ident} IS NOT NULL ORDER BY 1 LIMIT $1",
        limit,
    )
    return [str(r["value"]) for r in rows]


async def build_schema_card(
    conn: Connection,
    *,
    table: str = TABLE,
    value_columns: tuple[str, ...] = VALUE_COLUMNS,
    value_sample_limit: int = VALUE_SAMPLE_LIMIT,
) -> SchemaCard:
    """Introspect ``table`` into a :class:`SchemaCard` with value grounding.

    Pulls the column catalog from ``information_schema`` and, for each requested
    low-cardinality ``value_columns`` entry that actually exists in the table, a
    capped ``SELECT DISTINCT`` sample. Missing value columns are skipped (so the
    card stays valid against a schema that dropped one), not raised.
    """
    columns = await _fetch_columns(conn, table)
    present = {c.name for c in columns}
    value_samples: dict[str, list[str]] = {}
    for column in value_columns:
        if column not in present:
            continue
        value_samples[column] = await _fetch_value_sample(conn, table, column, value_sample_limit)
    return SchemaCard(table=table, columns=columns, value_samples=value_samples)


__all__ = [
    "ColumnInfo",
    "Connection",
    "SchemaCard",
    "TABLE",
    "VALUE_COLUMNS",
    "build_schema_card",
    "is_raw_column",
    "quote_identifier",
]
