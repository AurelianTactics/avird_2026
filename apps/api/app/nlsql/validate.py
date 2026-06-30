"""SQL validator: single safe SELECT, allow-listed, EXPLAIN-checked (plan P1, U3).

The structural gate that sits between the model and the read-only DB. It accepts
a candidate string **only** if it is exactly one read-only ``SELECT`` over the
allow-listed table(s), and proves it parses by ``EXPLAIN`` (not execute). It is
independent of the LLM — the same rules hold no matter what the model emits — and
it **never raises**: the agent loop reads ``ValidationResult.ok`` and repairs.

Layering (cheapest-first, fail-closed), mirroring the "trust the structure"
discipline of ``derived/filters.resolve``:

1. **Parse** with ``sqlglot`` (read-only, no execution) → exactly one statement.
2. **Read-only shape** → the statement is a query (SELECT/UNION/…), and no
   DML/DDL/command node appears anywhere (catches ``WITH x AS (DELETE …)`` and
   ``SELECT … INTO`` too).
3. **Table allow-list** → every real table is in the allow-list; ``pg_*`` and
   ``information_schema`` are refused by name (defense-in-depth — the read-only
   role also can't read them).
4. **LIMIT** → inject a default cap when the top-level query has none.
5. **EXPLAIN** → dry-run on the read-only connection to catch column typos and
   syntax with zero rows returned.

**Scope note (per the plan):** the structural gate owns table/schema/function
rejection + single-SELECT + LIMIT — the things ``EXPLAIN`` won't refuse. Column
*existence* is ``EXPLAIN``'s job (it errors on a bad column, returning no rows),
not a hard column allow-list here. The read-only role + table allow-list +
EXPLAIN are the real boundary; this module is the cheap, deterministic front.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import sqlglot
from sqlglot import exp

from .schema_card import TABLE

# Default row cap injected when a candidate has no top-level LIMIT, so a
# ``SELECT *`` over the whole table can't return an unbounded result set.
DEFAULT_LIMIT = 1000

ALLOWED_TABLES: frozenset[str] = frozenset({TABLE})

# Forbidden schemas/prefixes — refused by name even though the read-only role
# already blocks them, so a generated probe of the catalog fails loud and early.
_FORBIDDEN_SCHEMAS = frozenset({"information_schema", "pg_catalog"})
_FORBIDDEN_TABLE_PREFIX = "pg_"

# Any of these nodes anywhere in the tree means the candidate isn't a pure read.
_WRITE_NODES: tuple[type, ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.TruncateTable,
    exp.Merge,
    exp.Into,
    exp.Set,
    exp.Grant,
)


class ExplainConn(Protocol):
    """The async DB seam for the EXPLAIN dry-run: asyncpg's ``.execute``."""

    async def execute(self, query: str, *args: Any) -> Any: ...


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validation. ``normalized_sql`` is set only when ``ok``."""

    ok: bool
    reason: str = ""
    normalized_sql: str | None = None


def _reject(reason: str) -> ValidationResult:
    return ValidationResult(ok=False, reason=reason)


def validate_static(
    sql_text: str,
    *,
    allowed_tables: frozenset[str] = ALLOWED_TABLES,
    default_limit: int = DEFAULT_LIMIT,
) -> ValidationResult:
    """The DB-free structural gate (steps 1–4). Returns a normalized SQL on pass.

    Never raises: a parse failure or any rejected shape comes back as
    ``ok=False`` with a human-readable reason.
    """
    text = (sql_text or "").strip()
    if not text:
        return _reject("empty SQL")

    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except Exception as exc:  # noqa: BLE001 — sqlglot ParseError + friends
        return _reject(f"could not parse SQL: {type(exc).__name__}")

    if len(statements) == 0:
        return _reject("no statement found")
    if len(statements) > 1:
        return _reject("only a single statement is allowed (no ';'-chaining)")

    root = statements[0]

    # Read-only shape: no DML/DDL/command node anywhere (CTE-wrapped DML,
    # SELECT INTO, VACUUM/COPY-as-Command all get caught here).
    for node_type in _WRITE_NODES:
        if isinstance(root, node_type) or root.find(node_type) is not None:
            return _reject("only read-only SELECT statements are allowed")

    if not isinstance(root, exp.Query):
        return _reject("only SELECT queries are allowed")

    # Table allow-list. CTE-defined names are local aliases, not real tables —
    # exclude them so a legitimate WITH clause isn't mistaken for an unknown table.
    cte_names = {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}
    for table in root.find_all(exp.Table):
        schema = (table.db or "").lower()
        name = (table.name or "").lower()
        if schema in _FORBIDDEN_SCHEMAS or name.startswith(_FORBIDDEN_TABLE_PREFIX):
            return _reject(f"access to '{table.sql(dialect='postgres')}' is not allowed")
        if schema == "" and name in cte_names:
            continue
        if name not in {t.lower() for t in allowed_tables}:
            return _reject(f"table '{name}' is not in the allow-list")

    # Inject a default cap when the top-level query has no LIMIT.
    if root.args.get("limit") is None:
        root = root.limit(default_limit)

    return ValidationResult(ok=True, normalized_sql=root.sql(dialect="postgres"))


async def _explain_ok(conn: ExplainConn, sql: str) -> ValidationResult:
    """EXPLAIN the (already structurally valid) SQL — catches column/syntax errors.

    Uses ``execute`` (not ``fetch``): EXPLAIN returns plan rows, not table data,
    and we discard them — the dry-run touches no row of the table.
    """
    try:
        await conn.execute(f"EXPLAIN {sql}")
    except Exception as exc:  # noqa: BLE001 — asyncpg errors (UndefinedColumn, …)
        return _reject(f"EXPLAIN failed: {type(exc).__name__}")
    return ValidationResult(ok=True, normalized_sql=sql)


async def validate_sql(
    sql_text: str,
    *,
    conn: ExplainConn | None = None,
    allowed_tables: frozenset[str] = ALLOWED_TABLES,
    default_limit: int = DEFAULT_LIMIT,
) -> ValidationResult:
    """Full validation: static gate, then an optional ``EXPLAIN`` dry-run.

    When ``conn`` is ``None`` (no DB available), only the static gate runs — the
    structural guarantees still hold; column existence simply isn't checked.
    """
    static = validate_static(sql_text, allowed_tables=allowed_tables, default_limit=default_limit)
    if not static.ok or conn is None:
        return static
    return await _explain_ok(conn, static.normalized_sql or "")


__all__ = [
    "ALLOWED_TABLES",
    "DEFAULT_LIMIT",
    "ExplainConn",
    "ValidationResult",
    "validate_sql",
    "validate_static",
]
