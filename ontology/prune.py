'''Validation/pruning of raw LLM extractions against the frozen schema.

Everything here is deterministic. Narrative-extracted instances survive only
when:

1. their supporting quote verifies against the preprocessed narrative after
   normalization (casefold, whitespace collapse, punctuation folding). No
   plausible source span → drop as ``hallucination``; near-miss above the
   similarity threshold → drop as ``quote_mismatch``;
2. their entity/relationship label is declared by the schema;
3. relationships match a declared ``(source, REL, target)`` pattern — a
   reversed match is corrected (logged, as-emitted direction persisted), no
   match either way is dropped;
4. both relationship endpoints survived — otherwise ``dangling_relationship``.

Survivors get stable keys (see "Stable node keys" in the plan) and duplicate
within-narrative mentions collapse to one entity per key.
'''
import re
import sys
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

QUOTE_MISMATCH_THRESHOLD = 0.7

COUNTER_NAMES = (
    'hallucination', 'quote_mismatch', 'unknown_entity_label',
    'unknown_relationship_label', 'pattern_violation', 'direction_corrected',
    'dangling_relationship', 'duplicate_collapsed',
)

_PUNCT_RE = re.compile(r'[^\w\s]+')
_WS_RE = re.compile(r'\s+')


def normalize_for_quote(s):
    '''Casefold, fold punctuation to space, collapse whitespace.'''
    s = _PUNCT_RE.sub(' ', str(s).casefold())
    return _WS_RE.sub(' ', s).strip()


def verify_quote(quote, text, threshold=QUOTE_MISMATCH_THRESHOLD,
                 _normalized_text=None):
    '''Classify a supporting quote: ``ok`` | ``quote_mismatch`` | ``hallucination``.

    ``_normalized_text`` lets a caller verifying many quotes against the same
    document normalize it once instead of per quote.
    '''
    nq = normalize_for_quote(quote or '')
    nt = (_normalized_text if _normalized_text is not None
          else normalize_for_quote(text or ''))
    if not nq:
        return 'hallucination'
    if nq in nt:
        return 'ok'
    match = SequenceMatcher(None, nq, nt, autojunk=False).find_longest_match(
        0, len(nq), 0, len(nt))
    if match.size / len(nq) >= threshold:
        return 'quote_mismatch'
    return 'hallucination'


def normalize_name(name):
    return normalize_for_quote(name)


@dataclass
class PrunedEntity:
    key: str
    type: str
    name: str
    provenance: str                 # 'column' | 'narrative'
    quote: str = ''
    properties: dict = field(default_factory=dict)


@dataclass
class PrunedRelationship:
    type: str
    source_key: str
    target_key: str
    provenance: str
    quote: str = ''
    direction_corrected: bool = False
    as_emitted: dict | None = None  # {'source_key','target_key'} pre-correction


@dataclass
class PruneResult:
    entities: list
    relationships: list
    counters: dict
    dropped: list                   # human-readable drop log


class EntityKeyer:
    '''Stable-key assignment per the plan's "Stable node keys" decision.

    - Incident: the incident key itself.
    - Vehicle: subject by VIN (column seeding passes ``is_subject=True``),
      else ``<incident>:SV``; every other vehicle gets ``<incident>:V<n>`` —
      partner vehicles never collide with the subject's key.
    - Company: normalized name (column seeding passes ``master_entity``).
    - EnvironmentalCondition: normalized name, shared across incidents.
    - Anything else: ``<incident>:<Label>:<n>`` scoped per incident, one
      ordinal per distinct normalized name.
    '''

    def __init__(self, incident_key):
        self.incident_key = incident_key
        self._vehicle_ordinals = {}
        self._scoped_ordinals = {}

    def key_for(self, label, name, *, is_subject=False, vin=None):
        norm = normalize_name(name)
        if label == 'Incident':
            return self.incident_key
        if label == 'Company':
            return norm or f'{self.incident_key}:Company'
        if label == 'EnvironmentalCondition':
            return norm or f'{self.incident_key}:EnvironmentalCondition'
        if label == 'Vehicle':
            if is_subject:
                return vin or f'{self.incident_key}:SV'
            if norm not in self._vehicle_ordinals:
                self._vehicle_ordinals[norm] = len(self._vehicle_ordinals) + 1
            return f'{self.incident_key}:V{self._vehicle_ordinals[norm]}'
        scoped = self._scoped_ordinals.setdefault(label, {})
        if norm not in scoped:
            scoped[norm] = len(scoped) + 1
        return f'{self.incident_key}:{label}:{scoped[norm]}'


def prune_extraction(schema, raw, text, incident_key, keyer=None):
    '''Validate one doc's raw LLM extraction. Returns a PruneResult.

    ``raw`` carries ``entities`` (type/name/properties/supporting_quote) and
    ``relationships`` (type/source_type/source_name/target_type/target_name/
    supporting_quote) — the structured-output shape from extract.py.
    '''
    counters = {name: 0 for name in COUNTER_NAMES}
    dropped = []
    node_labels = {n.label for n in schema.node_types}
    rel_labels = {r.label for r in schema.relationship_types}
    patterns = set(schema.patterns)
    keyer = keyer or EntityKeyer(incident_key)
    normalized_text = normalize_for_quote(text or '')

    def drop(counter, detail):
        counters[counter] += 1
        dropped.append(f'{counter}: {detail}')

    surviving = {}          # (type, normalized name) -> PrunedEntity
    for ent in raw.entities:
        if ent.type not in node_labels:
            drop('unknown_entity_label', f'entity {ent.type}/{ent.name}')
            continue
        verdict = verify_quote(ent.supporting_quote, text,
                               _normalized_text=normalized_text)
        if verdict != 'ok':
            drop(verdict, f'entity {ent.type}/{ent.name} '
                          f'quote={ent.supporting_quote!r}')
            continue
        lookup = (ent.type, normalize_name(ent.name))
        if lookup in surviving:
            counters['duplicate_collapsed'] += 1
            existing = surviving[lookup]
            for k, v in (ent.properties or {}).items():
                existing.properties.setdefault(k, v)
            continue
        surviving[lookup] = PrunedEntity(
            key=keyer.key_for(ent.type, ent.name),
            type=ent.type,
            name=ent.name,
            provenance='narrative',
            quote=ent.supporting_quote,
            properties=dict(ent.properties or {}),
        )

    relationships = []
    for rel in raw.relationships:
        if rel.type not in rel_labels:
            drop('unknown_relationship_label', f'relationship {rel.type}')
            continue
        verdict = verify_quote(rel.supporting_quote, text,
                               _normalized_text=normalized_text)
        if verdict != 'ok':
            drop(verdict, f'relationship {rel.type} '
                          f'quote={rel.supporting_quote!r}')
            continue
        src = surviving.get((rel.source_type, normalize_name(rel.source_name)))
        dst = surviving.get((rel.target_type, normalize_name(rel.target_name)))
        if src is None or dst is None:
            drop('dangling_relationship',
                 f'{rel.source_type}/{rel.source_name} -{rel.type}-> '
                 f'{rel.target_type}/{rel.target_name}')
            continue
        corrected = False
        as_emitted = None
        if (src.type, rel.type, dst.type) not in patterns:
            if (dst.type, rel.type, src.type) in patterns:
                corrected = True
                as_emitted = {'source_key': src.key, 'target_key': dst.key}
                src, dst = dst, src
                counters['direction_corrected'] += 1
                dropped.append(f'direction_corrected: {rel.type} '
                               f'{as_emitted["source_key"]} <-> {dst.key}')
            else:
                drop('pattern_violation',
                     f'({src.type}, {rel.type}, {dst.type}) matches no pattern '
                     f'in either direction')
                continue
        relationships.append(PrunedRelationship(
            type=rel.type,
            source_key=src.key,
            target_key=dst.key,
            provenance='narrative',
            quote=rel.supporting_quote,
            direction_corrected=corrected,
            as_emitted=as_emitted,
        ))

    return PruneResult(
        entities=list(surviving.values()),
        relationships=relationships,
        counters=counters,
        dropped=dropped,
    )
