"""Local-first CLI for the NL→Cypher agent (plan P3, U15).

The iteration surface for learning: ask a question, watch the model author
Cypher against the ontology graph card, see each validation verdict, the
executed Cypher, the rows, and — when it fires — the repair loop.

    python -m app.kgquery.cli "which companies had pedestrian incidents?"
    python -m app.kgquery.cli --verbose "incidents at intersections"

Reads the ``NEO4J_*`` env contract for the graph (the Railway TCP-proxy
address for local dev). Uses the real Anthropic model when
``ANTHROPIC_API_KEY`` is set; otherwise a stub that echoes a canned
companies-by-incidents query, so the pipe is exercisable with no key. The
receipt-style output mirrors ``app/nlsql/cli.py``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from .agent import (
    MAX_ITERATIONS,
    ClaudeCypherModel,
    CypherModel,
    KgData,
    Neo4jKgData,
    run_kg_query,
)

# Canned query the keyless stub echoes — enough to exercise the full pipe
# (validate -> EXPLAIN -> read-mode execute -> render) without a model.
_STUB_CYPHER = (
    "MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle)<-[:INVOLVES]-(i:Incident) "
    "RETURN c.name AS company, count(DISTINCT i) AS incidents "
    "ORDER BY incidents DESC"
)


class StubCypherModel:
    """Keyless stand-in: echoes a fixed aggregation regardless of the question."""

    def author(self, system: str, user: str) -> str:
        return _STUB_CYPHER


def build_default_model() -> CypherModel:
    """Real model when a key is present, else the keyless stub."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return ClaudeCypherModel()
    print("[no ANTHROPIC_API_KEY] using the canned-Cypher stub model", file=sys.stderr)
    return StubCypherModel()


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
        print(f"  cypher: {attempt['cypher']}")
        if attempt.get("reason"):
            print(f"  reason: {attempt['reason']}")
    print("-" * 60)
    if not result.get("graph_available", True):
        print(f"GRAPH UNAVAILABLE: {result['message']}")
    elif result["fallback"]:
        print(f"FALLBACK: {result['message']}")
        if result.get("cypher"):
            print(f"  last attempted Cypher: {result['cypher']}")
    else:
        print(f"executed Cypher: {result['cypher']}")
        print(f"rows ({result['row_count']}):")
        print(_render_rows(result["rows"]))
    print("-" * 60)
    print(f"iterations: {result['iterations']}")


async def run_cli(
    question: str,
    *,
    data: KgData,
    model: CypherModel,
    max_iterations: int = MAX_ITERATIONS,
    verbose: bool = False,
) -> int:
    if verbose:
        try:
            card = data.graph_card()
            print("graph card:")
            print(card.render())
            print()
        except Exception as exc:  # noqa: BLE001
            print(f"[verbose] could not build graph card: {type(exc).__name__}", file=sys.stderr)
    result = await run_kg_query(question, data=data, model=model, max_iterations=max_iterations)
    _print_result(result)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    data: KgData | None = None,
    model: CypherModel | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question", help="The natural-language question to answer.")
    parser.add_argument("--verbose", action="store_true", help="Print the graph card too.")
    parser.add_argument(
        "--max-iterations", type=int, default=MAX_ITERATIONS, help="Repair-loop bound."
    )
    args = parser.parse_args(argv)

    try:
        if data is None:
            # Surface the NEO4J_* setup hint here: inside the agent an unreachable
            # graph is a silent first-class degrade, but for the local CLI a
            # missing env var should say exactly what to set.
            from .agent import get_neo4j_driver

            get_neo4j_driver()
            data = Neo4jKgData()
        model = model if model is not None else build_default_model()
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
        # e.g. NEO4J_* unset — a one-line hint, not a traceback.
        print(f"[kgquery.cli] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
