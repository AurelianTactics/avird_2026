"""Cypher validator: single safe read-only statement, allow-listed, EXPLAIN-checked (P3, U14).

The structural gate between the model and the graph. Unlike P1 there is **no
read-only credential** to lean on — Neo4j Community Edition has no role
management — so the runtime floor is the read-access-mode transaction the data
seam enforces (``execute_query(routing_=READ)``, see ``agent.py``). This module
is the cheap deterministic front sitting on top of that floor, mirroring
``app/nlsql/validate.py``: it **never raises** on bad input — the agent loop
reads ``ValidationResult.ok`` and repairs.

Layering (cheapest-first, fail-closed):

1. **Single statement** — reject ``;``-chaining (one trailing ``;`` tolerated).
2. **Write-clause rejection** — ``CREATE``/``MERGE``/``DELETE``/``DETACH``/
   ``SET``/``REMOVE``/``FOREACH``/``DROP``/``LOAD CSV`` anywhere, scanned with
   string literals stripped so a narrative quote can't false-trip it.
3. **CALL rejected wholesale** — procedures are where read-only guarantees leak
   (``apoc.*``, ``db.*`` and friends), so no ``CALL`` of any kind.
4. **Label/relationship allow-list** — every ``:Token`` must be in the schema
   vocabulary from the graph card. Backtick identifiers are rejected outright:
   the schema's labels are all plain identifiers, and backticks are how an
   off-vocabulary token would sneak past this check.
5. **LIMIT** — inject a default cap when the statement has none.
6. **EXPLAIN** — dry-run on a read-mode session to catch syntax/semantic errors
   with zero execution (Neo4j's EXPLAIN plans without running).

Scope note: the token scan is a keyword gate, not a Cypher parser. A label
written with whitespace after the colon (``: Company``) slips the allow-list
check but still faces EXPLAIN + the read-mode floor + a graph that simply has
no such label — defense-in-depth, same posture as nlsql's column scope note.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .graph_card import load_graph_card

# Default row cap injected when a candidate has no LIMIT, so a broad MATCH
# can't return an unbounded result set.
DEFAULT_LIMIT = 200

# Write clauses (and their unmistakable fragments), rejected anywhere outside a
# string literal. DETACH/FOREACH only exist in write contexts; DROP covers
# schema DDL; LOAD CSV is its own import clause.
_WRITE_CLAUSE_RE = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|FOREACH|DROP)\b|\bLOAD\s+CSV\b",
    re.IGNORECASE,
)

_CALL_RE = re.compile(r"\bCALL\b", re.IGNORECASE)
_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)

# String literals (single or double quoted, with backslash escapes) are blanked
# before any keyword/token scan so data values can't trip or hide a check.
_STRING_LITERAL_RE = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")

# A map-literal key looks exactly like a label token to a colon scan
# (`{name:n.name}` vs `(n:Incident)`). The disambiguator is what precedes the
# key identifier: map keys follow `{` or `,`; label positions follow `(`, `[`,
# or a bare variable. Blanking the key's colon before the token scan keeps
# idiomatic tight map projections from being rejected as unknown labels.
_MAP_KEY_RE = re.compile(r"([{,]\s*[A-Za-z_][A-Za-z0-9_]*\s*):")

# A label/relationship token expression: `:Ident`, optionally continued as an
# alternation (`:A|B`, `:A | :B`) — every alternative must face the allow-list,
# not just the first (a `|`-smuggled off-schema type would otherwise skip it).
_TOKEN_RE = re.compile(r":\s*([A-Za-z_][A-Za-z0-9_]*(?:\s*\|\s*:?\s*[A-Za-z_][A-Za-z0-9_]*)*)")
_TOKEN_SPLIT_RE = re.compile(r"[|:\s]+")

# Map values that still slip through (e.g. after an unusual key shape) can be
# bare value keywords; these are never labels, so they're exempt.
_VALUE_KEYWORDS = frozenset({"true", "false", "null"})


class Explainer(Protocol):
    """The async EXPLAIN seam: raises on invalid Cypher, returns None when it plans.

    The real implementation (``agent.KgData.explain``) runs ``EXPLAIN <cypher>``
    inside a read-access-mode session; tests inject a fake.
    """

    async def explain(self, cypher: str) -> None: ...


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validation. ``normalized_cypher`` is set only when ``ok``."""

    ok: bool
    reason: str = ""
    normalized_cypher: str | None = None


def _reject(reason: str) -> ValidationResult:
    return ValidationResult(ok=False, reason=reason)


def validate_static(
    cypher_text: str,
    *,
    allowed_labels: frozenset[str] | None = None,
    allowed_relationships: frozenset[str] | None = None,
    default_limit: int = DEFAULT_LIMIT,
) -> ValidationResult:
    """The graph-free structural gate (steps 1–5). Returns normalized Cypher on pass.

    ``allowed_labels`` / ``allowed_relationships`` default to the frozen schema's
    vocabulary via :func:`load_graph_card`; tests pass explicit sets.
    """
    text = (cypher_text or "").strip()
    if not text:
        return _reject("empty Cypher")

    # One trailing semicolon is tolerated (models add it); any other ';' means
    # statement chaining.
    text = text.rstrip().rstrip(";").rstrip()
    if not text:
        return _reject("empty Cypher")

    scannable = _STRING_LITERAL_RE.sub("''", text)

    if ";" in scannable:
        return _reject("only a single statement is allowed (no ';'-chaining)")

    if "`" in scannable:
        return _reject("backtick-quoted identifiers are not allowed")

    write_hit = _WRITE_CLAUSE_RE.search(scannable)
    if write_hit:
        clause = write_hit.group(0).upper()
        return _reject(f"write clause '{clause}' is not allowed — read-only Cypher only")

    if _CALL_RE.search(scannable):
        return _reject("CALL is not allowed (procedures are not read-only-safe)")

    if allowed_labels is None or allowed_relationships is None:
        card = load_graph_card()
        if allowed_labels is None:
            allowed_labels = card.allowed_labels
        if allowed_relationships is None:
            allowed_relationships = card.allowed_relationships
    known = allowed_labels | allowed_relationships
    token_scannable = _MAP_KEY_RE.sub(r"\1 ", scannable)
    for expression in _TOKEN_RE.findall(token_scannable):
        for token in _TOKEN_SPLIT_RE.split(expression):
            if not token or token.lower() in _VALUE_KEYWORDS:
                continue
            if token not in known:
                return _reject(f"'{token}' is not a label or relationship in the graph schema")

    if not _LIMIT_RE.search(scannable):
        text = f"{text} LIMIT {default_limit}"

    return ValidationResult(ok=True, normalized_cypher=text)


async def _explain_ok(explainer: Explainer, cypher: str) -> ValidationResult:
    """EXPLAIN the (already structurally valid) Cypher — catches syntax/semantics.

    Neo4j's EXPLAIN produces a plan without executing, so the dry-run touches no
    data and returns no rows.
    """
    try:
        await explainer.explain(cypher)
    except Exception as exc:  # noqa: BLE001 — neo4j CypherSyntaxError + friends
        return _reject(f"EXPLAIN failed: {type(exc).__name__}")
    return ValidationResult(ok=True, normalized_cypher=cypher)


async def validate_cypher(
    cypher_text: str,
    *,
    explainer: Explainer | None = None,
    allowed_labels: frozenset[str] | None = None,
    allowed_relationships: frozenset[str] | None = None,
    default_limit: int = DEFAULT_LIMIT,
) -> ValidationResult:
    """Full validation: static gate, then an optional ``EXPLAIN`` dry-run.

    When ``explainer`` is ``None`` (no live graph), only the static gate runs —
    the structural guarantees still hold; syntax simply isn't machine-proved.
    """
    static = validate_static(
        cypher_text,
        allowed_labels=allowed_labels,
        allowed_relationships=allowed_relationships,
        default_limit=default_limit,
    )
    if not static.ok or explainer is None:
        return static
    return await _explain_ok(explainer, static.normalized_cypher or "")


__all__ = [
    "DEFAULT_LIMIT",
    "Explainer",
    "ValidationResult",
    "validate_cypher",
    "validate_static",
]
