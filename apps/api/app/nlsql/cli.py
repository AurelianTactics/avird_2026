"""Local-first CLI for the text-to-SQL agent (plan P1, U5).

The iteration surface for learning: ask a question, watch the model author SQL,
see each validation verdict, the executed SQL, the rows, and — when it fires —
the repair loop. No route, no public surface; this drives the agent against the
seeded local DB through the read-only role.

    python -m app.nlsql.cli "which companies had the most fatal incidents?"
    python -m app.nlsql.cli --verbose "incidents in Arizona"

Reads ``READONLY_DATABASE_URL`` for the data layer. Uses the real Anthropic model
when ``ANTHROPIC_API_KEY`` is set; otherwise falls back to a stub that echoes a
canned aggregation query, so the pipe is exercisable with no key (it just won't
answer arbitrary questions). The receipt-style output mirrors
``eda/build_narrative_embeddings.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from .agent import MAX_ITERATIONS, ClaudeSqlModel, NlSqlData, SqlData, SqlModel, run_sql_query

# Canned query the keyless stub echoes — enough to exercise the full pipe
# (validate -> execute -> render) against the seeded DB without a model.
_STUB_SQL = (
    "SELECT master_entity, COUNT(*) AS n FROM treated_incident_reports "
    "WHERE \"Highest Injury Severity Alleged\" = 'Fatality' "
    "GROUP BY master_entity ORDER BY n DESC"
)


class StubSqlModel:
    """Keyless stand-in: echoes a fixed aggregation regardless of the question."""

    def author(self, system: str, user: str) -> str:
        return _STUB_SQL


def build_default_model() -> SqlModel:
    """Real model when a key is present, else the keyless stub."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeSqlModel()
    print("[no ANTHROPIC_API_KEY] using the canned-SQL stub model", file=sys.stderr)
    return StubSqlModel()


def _render_rows(rows: list[dict[str, Any]], *, limit: int = 50) -> str:
    if not rows:
        return "  (no rows)"
    headers = list(rows[0].keys())
    widths = {h: len(str(h)) for h in headers}
    shown = rows[:limit]
    for row in shown:
        for h in headers:
            widths[h] = max(widths[h], len(str(row.get(h, ""))))
    line = "  " + " | ".join(str(h).ljust(widths[h]) for h in headers)
    sep = "  " + "-+-".join("-" * widths[h] for h in headers)
    out = [line, sep]
    for row in shown:
        out.append("  " + " | ".join(str(row.get(h, "")).ljust(widths[h]) for h in headers))
    if len(rows) > limit:
        out.append(f"  … {len(rows) - limit} more row(s)")
    return "\n".join(out)


def _print_result(result: dict[str, Any]) -> None:
    print("=" * 60)
    print(f"question: {result['question']}")
    print("=" * 60)
    for attempt in result.get("attempts", []):
        print(f"--- attempt {attempt['iteration']} [{attempt['status']}] ---")
        print(f"  sql: {attempt['sql']}")
        if attempt.get("reason"):
            print(f"  reason: {attempt['reason']}")
    print("-" * 60)
    if result["fallback"]:
        print(f"FALLBACK: {result['message']}")
        if result.get("sql"):
            print(f"  last attempted SQL: {result['sql']}")
    else:
        print(f"executed SQL: {result['sql']}")
        print(f"rows ({result['row_count']}):")
        print(_render_rows(result["rows"]))
    print("-" * 60)
    print(f"iterations: {result['iterations']}")


async def run_cli(
    question: str,
    *,
    data: SqlData,
    model: SqlModel,
    max_iterations: int = MAX_ITERATIONS,
    verbose: bool = False,
) -> int:
    if verbose:
        try:
            card = await data.schema_card()
            print("schema card:")
            print(card.render())
            print()
        except Exception as exc:  # noqa: BLE001
            print(f"[verbose] could not build schema card: {type(exc).__name__}", file=sys.stderr)
    result = await run_sql_query(question, data=data, model=model, max_iterations=max_iterations)
    _print_result(result)
    return 0


def main(
    argv: list[str] | None = None, *, data: SqlData | None = None, model: SqlModel | None = None
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", help="The natural-language question to answer.")
    parser.add_argument("--verbose", action="store_true", help="Print the schema card too.")
    parser.add_argument(
        "--max-iterations", type=int, default=MAX_ITERATIONS, help="Repair-loop bound."
    )
    args = parser.parse_args(argv)

    data = data if data is not None else NlSqlData()
    model = model if model is not None else build_default_model()
    try:
        return asyncio.run(
            run_cli(
                args.question,
                data=data,
                model=model,
                max_iterations=args.max_iterations,
                verbose=args.verbose,
            )
        )
    except RuntimeError as exc:
        # e.g. READONLY_DATABASE_URL unset — a one-line hint, not a traceback.
        print(f"[nlsql.cli] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
