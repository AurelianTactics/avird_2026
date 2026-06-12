# Golden annotation guidelines

**Version: v0.1** (pre-labeling draft — bump the version on any ruling change
and record the change in the log below). Every golden record carries the
`guidelines_version` it was annotated under.

## Scope

- Golden labels cover the **narrative universe only**. Column-derived
  instances (subject vehicle make/model, company, date, location columns) are
  excluded from extraction scoring, so do not annotate facts the structured
  columns already carry — annotate what the *narrative* adds.
- Annotate against the **frozen schema** (`ontology/schema/v001.yaml`).
  Entity `type` must be a schema label or `UNMAPPED`.

## What counts as an entity

- A mention counts when the narrative names a discrete participant, object,
  or condition that a schema node type expresses (pedestrian, cyclist,
  another vehicle, traffic control, etc.).
- Generic scene-setting ("traffic was heavy") is not an entity unless a
  schema type captures it.
- Collapse repeated mentions of the same referent to **one entity** per doc
  (matching extraction's per-key collapse). Two *distinct* pedestrians are
  two entities with distinct keys (`<incident>:Pedestrian:1`, `:2`).

## Quote conventions

- `quote` is copied **verbatim** from the preprocessed narrative (the `text`
  field of the record) — the shortest span that supports the annotation.
- Quotes are compared after normalization (casefold, whitespace collapse,
  punctuation folding), so exact capitalization doesn't matter; missing or
  paraphrased words do.

## Crash-partner vehicles

- The subject vehicle is column-derived — do not annotate it unless the
  narrative adds a relationship (e.g. COLLIDED_WITH) or property.
- Partner vehicles annotated from the narrative get keys
  `<incident>:V1`, `<incident>:V2`, ... in order of first mention; they never
  reuse the subject vehicle's key.

## UNMAPPED

- A salient mention no schema type expresses gets `type: "UNMAPPED"` with a
  free-text `candidate_type` (e.g. `"EmergencyResponder"`). These feed the
  schema-coverage metric (mapped / (mapped + UNMAPPED)) and future schema
  revisions. UNMAPPED entities take no relationships.

## Splits

- `dev.jsonl` (~10 docs): prompt iteration allowed.
- `heldout.jsonl` (~30+ docs): **final numbers only** — never look at
  per-doc predictions on this split while iterating; `evaluate.py` refuses it
  without `--heldout`.

## Ambiguous-case rulings

> Record every judgment call made while correcting, so future re-annotation
> is consistent. (To be filled during the labeling pass.)

- *(none yet)*

## Intra-annotator agreement

> After a 1-2 week gap, re-annotate ~10 docs and record agreement here.

- *(not yet measured)*

## Change log

- v0.1 (2026-06-12): initial draft written before labeling.
