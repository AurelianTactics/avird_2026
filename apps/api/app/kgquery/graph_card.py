"""Graph card: render ``ontology/schema/v001.yaml`` into grounding context (P3, U14).

The NL→Cypher model can only be as right as the vocabulary it's given. The
ontology schema is small and enumerable — that's the whole point of the graph —
so the card embeds **all** of it: node labels (with their typed properties),
relationship types, and the ``patterns`` triples that say which label connects
to which. The same parse also yields the structured label/relationship
allow-lists the validator (``validate.py``) checks candidate Cypher against —
card and allow-list can never drift because they come from one read.

This module parses the yaml **directly with pyyaml** and never imports ontology
modules (the same isolation call as P2's vendored cosine: the api stays free of
the ontology sidecar env). The schema file is committed and frozen
(``schema/drafts/`` discipline), so reading it at startup from a repo-relative
path is stable; a module-level memo makes repeat loads free.

Mirrors ``app/nlsql/schema_card.py`` (card + allow-list dual output, memo).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# apps/api/app/kgquery/graph_card.py -> repo root is four levels up from app/.
REPO_ROOT = Path(__file__).resolve().parents[4]
SCHEMA_PATH = REPO_ROOT / "ontology" / "schema" / "v001.yaml"

# Every loaded node carries these two properties regardless of label —
# graph_load.py merges on `key` and always sets `name` from the extraction.
UNIVERSAL_PROPERTIES = ("key", "name")


@dataclass(frozen=True)
class NodeType:
    label: str
    description: str
    properties: tuple[tuple[str, str], ...]  # (name, type)


@dataclass(frozen=True)
class RelationshipType:
    label: str
    description: str


@dataclass(frozen=True)
class GraphCard:
    """The grounding context + the structured allow-lists the validator consumes."""

    version: str
    node_types: tuple[NodeType, ...]
    relationship_types: tuple[RelationshipType, ...]
    patterns: tuple[tuple[str, str, str], ...]  # (source, relationship, target)

    @property
    def allowed_labels(self) -> frozenset[str]:
        return frozenset(n.label for n in self.node_types)

    @property
    def allowed_relationships(self) -> frozenset[str]:
        return frozenset(r.label for r in self.relationship_types)

    def render(self) -> str:
        """A compact text card for the system prompt."""
        lines = [
            f"Graph schema ({self.version}).",
            f"Every node carries {' and '.join(f'`{p}`' for p in UNIVERSAL_PROPERTIES)} "
            "(string) in addition to the properties listed below; `name` is the "
            "human-readable display value to RETURN and filter on.",
            "",
            "Node labels (label — extra properties):",
        ]
        for node in self.node_types:
            props = ", ".join(f"{name} ({ptype})" for name, ptype in node.properties)
            suffix = f" — {props}" if props else ""
            lines.append(f"  - {node.label}{suffix}")
        lines.append("")
        lines.append("Relationship types:")
        for rel in self.relationship_types:
            desc = f" — {rel.description}" if rel.description else ""
            lines.append(f"  - {rel.label}{desc}")
        lines.append("")
        lines.append("Connection patterns (only these shapes exist in the graph):")
        for source, relationship, target in self.patterns:
            lines.append(f"  ({source})-[:{relationship}]->({target})")
        return "\n".join(lines)


def parse_graph_card(data: dict) -> GraphCard:
    """Build a :class:`GraphCard` from the parsed yaml dict (pure, test seam)."""
    node_types = tuple(
        NodeType(
            label=n["label"],
            description=n.get("description") or "",
            properties=tuple(
                (p["name"], p.get("type") or "STRING") for p in (n.get("properties") or [])
            ),
        )
        for n in data.get("node_types") or []
    )
    relationship_types = tuple(
        RelationshipType(label=r["label"], description=r.get("description") or "")
        for r in data.get("relationship_types") or []
    )
    patterns = tuple((p[0], p[1], p[2]) for p in (data.get("patterns") or []) if len(p) == 3)
    return GraphCard(
        version=str(data.get("version") or "unknown"),
        node_types=node_types,
        relationship_types=relationship_types,
        patterns=patterns,
    )


_CARD: GraphCard | None = None


def load_graph_card(path: Path = SCHEMA_PATH) -> GraphCard:
    """Load (and memoize) the frozen schema. A missing file raises a one-line
    setup hint, not a bare traceback — the routes degrade on it."""
    global _CARD
    if _CARD is not None and path == SCHEMA_PATH:
        return _CARD
    try:
        with Path(path).open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"ontology schema not found at {path} — the kgquery card is built from "
            "the committed ontology/schema/v001.yaml (frozen schema discipline)."
        ) from exc
    card = parse_graph_card(data)
    if path == SCHEMA_PATH:
        _CARD = card
    return card


__all__ = [
    "SCHEMA_PATH",
    "UNIVERSAL_PROPERTIES",
    "GraphCard",
    "NodeType",
    "RelationshipType",
    "load_graph_card",
    "parse_graph_card",
]
