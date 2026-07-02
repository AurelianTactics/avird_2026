# kgquery golden set

Seeded from the 18 **competency questions** in `ontology/schema/v001.yaml`
(lines 830–848) — the questions the schema was designed to answer — split
~12 dev / 6 held-out, plus three deliberately-unanswerable rows (questions
needing labels/properties outside the schema; the correct behavior is the
refusal contract `RETURN NULL LIMIT 0`).

Row shape:

```json
{"question": "...", "gold_cypher": "MATCH ... RETURN ...", "kind": "aggregation"}
{"question": "...", "gold_cypher": "RETURN NULL LIMIT 0", "unanswerable": true}
```

Rules (mirrors `golden/nlsql/`):

- **Held-out is final-numbers-only** — `tools/eval_kgquery.py` refuses
  `heldout.jsonl` without `--heldout`. Iterate prompts against dev.
- The metric is **answer-set equivalence** (order-insensitive rows, floats
  rounded) plus answer-set F1 partial credit — gold and candidate Cypher are
  both executed read-mode against the live graph and compared by results,
  never by query text.
- Answers cover the **extracted subgraph (n≈143 incidents)** from the
  2026-06-18 extraction run, not the full treated table — gold answers are
  authored against that same subgraph so the eval is internally consistent.
- The gold Cypher was authored from the frozen schema's patterns **before the
  Railway graph existed**; on first live run, sanity-check each gold query's
  rows (`python -m app.kgquery.cli` helps) and adjust value-matching
  (severity/state spellings) where the extraction's property values differ.
