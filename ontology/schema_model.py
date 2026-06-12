'''Pydantic models for the YAML ontology schema + load/dump helpers.

The YAML shape mirrors neo4j-graphrag's ``GraphSchema`` (``node_types`` /
``relationship_types`` / ``patterns``) extended with ``version``, per-type
``provenance`` (``column`` = seeded deterministically from structured columns,
``narrative`` = LLM-discovered), and ``competency_questions``.

Frozen schemas live at ``ontology/schema/vNNN.yaml`` and are never edited in
place; drafts live under ``ontology/schema/drafts/``. Extraction must load via
``load_frozen_schema``, which refuses draft paths.
'''
import sys
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

PROPERTY_TYPES = ('STRING', 'INTEGER', 'FLOAT', 'BOOLEAN', 'DATE', 'DATETIME')
Provenance = Literal['column', 'narrative']


class PropertySpec(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str
    type: Literal[PROPERTY_TYPES] = 'STRING'
    description: str = ''
    required: bool = False


class NodeType(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str
    description: str = ''
    provenance: Provenance
    properties: list[PropertySpec] = Field(default_factory=list)


class RelationshipType(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str
    description: str = ''
    provenance: Provenance
    properties: list[PropertySpec] = Field(default_factory=list)


class OntologySchema(BaseModel):
    model_config = ConfigDict(extra='forbid')

    version: str
    description: str = ''
    node_types: list[NodeType]
    relationship_types: list[RelationshipType] = Field(default_factory=list)
    patterns: list[tuple[str, str, str]] = Field(default_factory=list)
    competency_questions: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def _check_references(self):
        node_labels = [n.label for n in self.node_types]
        rel_labels = [r.label for r in self.relationship_types]
        for labels, kind in ((node_labels, 'node'), (rel_labels, 'relationship')):
            dupes = {x for x in labels if labels.count(x) > 1}
            if dupes:
                raise ValueError(f'duplicate {kind} labels: {sorted(dupes)}')
        nodes, rels = set(node_labels), set(rel_labels)
        for source, rel, target in self.patterns:
            if source not in nodes:
                raise ValueError(f'pattern source {source!r} is not a declared node type')
            if target not in nodes:
                raise ValueError(f'pattern target {target!r} is not a declared node type')
            if rel not in rels:
                raise ValueError(f'pattern relationship {rel!r} is not a declared relationship type')
        return self

    def node_type(self, label):
        for n in self.node_types:
            if n.label == label:
                return n
        raise KeyError(label)


def load_schema(path):
    '''Load + validate a schema YAML. Empty or null files raise loudly.'''
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding='utf-8'))
    if data is None:
        raise ValueError(f'schema file is empty: {path}')
    return OntologySchema.model_validate(data)


def load_frozen_schema(path):
    '''Load a schema for extraction/eval — refuses anything under drafts/.'''
    path = Path(path)
    if 'drafts' in path.parts:
        raise ValueError(
            f'refusing to load a draft schema for extraction: {path}. '
            f'Approve it first (save as ontology/schema/vNNN.yaml and commit).'
        )
    return load_schema(path)


def dump_schema(schema, path, header=None):
    '''Write a schema as YAML (key order preserved, ambiguous scalars quoted).'''
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(
        schema.model_dump(mode='json'),
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    text = (header.rstrip() + '\n' if header else '') + body
    path.write_text(text, encoding='utf-8', newline='\n')
    return path
