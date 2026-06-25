# Golden annotation guidelines

**Version: v0.2** (first hand-correction pass complete — bump the version on any
ruling change and record the change in the log below). Every golden record
carries the `guidelines_version` it was annotated under.

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
> is consistent.

- **Column-scaffold concepts are not re-annotated from the narrative.** The
  `Incident`, `Company`, `Location`, and `EnvironmentalCondition` nodes (and
  their `INVOLVES` / `OPERATED_BY`→Company / `REPORTED_BY` / `OCCURRED_AT`→Location
  / `HAD_CONDITION` edges) come from the structured columns. Narrative copies of
  them were dropped, including narrative-only conditions (e.g. "exhaust fumes",
  "heavy pedestrian traffic", "vegetation occlusion") and mis-typed timestamps
  ("8:43 PM PT") the pre-labeler had filed under `EnvironmentalCondition`.
- **Subject vehicle uses its column VIN key.** The reporting company's AV is
  column-seeded; its narrative facts (`TRAVELING_IN`, `CONTROLLED_BY`,
  `COLLIDED_WITH`, …) are attached to the VIN key, not to a narrative `:Vn`
  partner key. `evaluate.py` identity-maps column keys, so this is required for
  relationship scoring. Crash-partner vehicles keep `:Vn` keys (incl. a *second*
  AV when one appears — e.g. doc `3f40494138fe83f`).
- **Cyclists / e-scooter riders are `UNMAPPED`.** The schema has no node for a
  cyclist or e-scooterist (a `Pedestrian` is on foot), so these vulnerable road
  users get `type: UNMAPPED` with `candidate_type` `Cyclist` / `EScooterRider`
  and, per the UNMAPPED rule, carry no relationships. This feeds the
  schema-coverage metric and flags a v002 gap. On-foot pedestrians stay
  `Pedestrian`. The pre-labeler's duplicate `Vehicle` "Cyclist Vehicle" /
  "e-scooter" nodes were removed.
- **Absence and disposition are not entities.** "No injuries", "passenger not
  belted", "not transported from the scene" are not `Injuryseverity`
  annotations; "towed away" is a post-incident disposition, not a
  `Vehiclestate`; damage is annotated only when the narrative states damage was
  sustained (so doc `01fe1096ad10e2c`'s low-speed curb touch carries no
  `Damage`). "Cross-traffic" is not a `Trafficcontrol`.
- **Self-referential and unsupported edges dropped**, e.g.
  `ATTEMPTED_MANEUVER (subject → subject)` and a `STOPPED_AT` linking a trailing
  vehicle to a stoplight it never stopped at.

## Intra-annotator agreement

> After a 1-2 week gap, re-annotate ~10 docs and record agreement here.

- *(not yet measured)*

## Change log

- v0.1 (2026-06-12): initial draft written before labeling.
- v0.2 (2026-06-18): first hand-correction pass over `dev.jsonl` (10 docs) and
  `heldout.jsonl` (35 docs). Added the ambiguous-case rulings above; corrected
  all 45 records accordingly. `golden.py check` passes.
