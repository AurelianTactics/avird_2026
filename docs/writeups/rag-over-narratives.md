# RAG over narratives (agentic data-access P2)

The second phase of the [agentic data-access progression](../plans/2026-06-30-001-feat-agentic-data-access-progression-plan.md). Where P1 authored structured SQL, P2 does **semantic retrieval + grounded generation**: retrieve the crash narratives relevant to a question, answer from them, and **cite the incidents used** — reusing the existing `bge-base` embedding cache.

## What shipped

A local-first narrative-RAG agent (`app/rag/`), no public route:

```bash
python db/pgvector_setup.sql          # optional: pgvector store (else in-memory)
python -m app.rag.cli --dataset-id <id> "pedestrian in a crosswalk at night"
python -m app.rag.cli --pgvector --judge "rear-end collisions while stopped"
python tools/eval_rag.py --dataset-id <id>   # citation + coverage numbers
```

The pieces:

- **Store** (`store.py`, U8) — one `retrieve(query_embedding, k)` signature over two backends: `PgVectorStore` (`embedding <=> $1` cosine) and an `InMemoryStore` (vendored numpy cosine, with MMR diversification so resubmissions of one incident don't crowd the top-k). Cosine is vendored rather than pulled from `eda` so the api takes no scikit-learn dependency.
- **Ingest** (`ingest.py`, U8) — the real work: the embedding cache stores only `{text_hash, vector}`, so incident id + narrative are **re-derived** from the raw CSVs via the `eda` dedup pipeline, re-hashed, and joined to the cache vector by hash. Misses are reported, never dropped.
- **Context** (`context.py`, U9) — numbered `[n] (incident <id>): …` chunks with an `id_map`, deduped by incident, truncated to a budget. The numbering is the contract the citation gate depends on.
- **Agent** (`agent.py`, U10) — `embed → retrieve → assemble → generate → validate_citations → faithfulness_judge → respond`, with re-retrieve-and-regenerate repair bounded by `max_iterations` + budget.
- **Golden** (`golden/rag/`, `eval_rag.py`, U11) — citation recall/precision + answer-point coverage, held-out-guarded.

## Why these choices

- **Two validation tiers, deliberately different (the key lesson).** Citation existence is a **cheap, deterministic, always-on structural gate**: every `[n]` must resolve to a retrieved chunk via the `id_map`, and a fabricated `[9]` is caught and stripped — a made-up citation *never* leaves the agent. Faithfulness is an **expensive, model-judged tier** (a larger model per KTD-7, the debate-judge pattern generalized) that asks whether each claim is actually backed. The structural gate is the floor you always run; the judge is opt-in (`--judge`) because it's a second paid call per answer. This is the RAG analogue of P1's "read-only role vs validator" split: trust the cheap structure first, spend on the model-judgment second.
- **pgvector with an in-memory fallback (KTD-3).** Real retrieval learning wants pgvector, but stock Windows PG 17 may not bundle the extension, so the same `retrieve` signature has a zero-setup numpy path. Neither blocks local iteration.
- **Query embedding computed outside the store.** The store never imports `huggingface_hub`; the agent's embedding adapter (lazy HF) produces the query vector and passes it in. Keeps the retrieval backbone dependency-light and the whole loop fakeable in tests.

## What surprised / sharp edges

- **"Load the parquet" is a trap.** The cache has no incident id and no narrative text — only a hash and a vector. Re-deriving the deduped rows from the CSVs and joining by the *same* hash the cache was written with is the actual ingest; a test cross-checks that `rag/ingest._text_hash` equals `eda_utils_embed._text_hash`, because if they drifted every row would be reported unmatched.
- **The structural citation gate does most of the safety work for almost no cost.** It's deterministic and always on; the faithfulness judge is where the money goes, so it's gated. Separating "did it cite a real chunk" from "is the claim true" made both the code and the eval clearer.
- **Empty retrieval is a refusal, not an error.** If nothing relevant is retrieved the agent returns `NOT SUPPORTED BY THE DATA` and never calls the answer model — counted as correct behavior by the golden set.

## What's deferred

- **Live exposure.** P2 ships no route. `POST /rag/ask` (proxy + `RAG_DAILY_BUDGET_USD` guard) is a separate gated decision.
- **Dependency weight.** Per R22 and the "api stays ML-free" invariant, the RAG toolchain deps (`numpy`, `pandas`, `pyarrow`, `huggingface_hub`) are **not** in `apps/api`'s production `pyproject.toml` — they're lazy-imported, live in the shared dev env, and `rag/` is never loaded by the FastAPI app. The live-exposure unit adds runtime deps when a real route needs them.
- **Golden labeling + numbers.** `expected_incident_ids` ship unlabeled (`[]`) — the right ids depend on the seeded corpus and are hand-picked via the CLI (see `golden/rag/README.md`); unlabeled rows are scored on coverage only and excluded from the citation means. The committed summary lands under `tools/results/` once run with the cache + keys.
- **LLM-judge coverage.** Answer-point coverage is deterministic keyword matching for a reproducible number; an LLM-judged variant (temperature 0, documented as non-deterministic) is a possible follow-up.
