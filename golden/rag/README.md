# RAG golden set (plan P2, U11)

`dev.jsonl` / `heldout.jsonl` score the narrative-RAG agent on two axes: **citation
recall/precision** (did it cite the incidents a human judged relevant) and
**answer-point coverage** (did the answer hit the points it should). Held-out is
final-numbers-only — `tools/eval_rag.py` refuses it without `--heldout`.

## Row shape

```jsonc
{"question": "...", "expected_incident_ids": ["..."], "answer_points": ["rear-ended", "stopped"]}
{"question": "...", "unsupported": true}   // narratives can't answer -> a refusal is correct
```

## Hand-labeling `expected_incident_ids`

These ship **unlabeled** (`[]`) on purpose — the right incident ids depend on the
seeded corpus, so they're picked by review, the way `ontology/golden.py` records
are hand-corrected. To label a row:

1. Run the retriever for the question and read the top incidents:
   ```bash
   python -m app.rag.cli --dataset-id <id> "Describe a crash where the AV was rear-ended while stopped."
   ```
2. Put the incident ids that genuinely answer the question into
   `expected_incident_ids`.

Rows left unlabeled are scored on **coverage only** and excluded from the citation
means (`n_labeled` in the summary tells you how many count toward those numbers),
so the harness is honest about how much of the set is actually labeled.
