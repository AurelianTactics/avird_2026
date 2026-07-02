# Knowledge-graph queries: NL → Cypher (agentic data-access P3)

The third phase of the [agentic data-access progression](../plans/2026-06-30-001-feat-agentic-data-access-progression-plan.md): P1's execute-observe-repair loop transferred from SQL over Postgres to **Cypher over the Neo4j ontology graph** — the property graph extracted from SGO crash narratives against the frozen `ontology/schema/v001.yaml`.

## What shipped

An NL→Cypher agent (`app/kgquery/`), with the web surface planned up front this time (the P1/P2 lesson: both phases "deferred" the route and both shipped one after iteration):

```bash
# ask a question (real model when ANTHROPIC_API_KEY is set, else a canned stub)
python -m app.kgquery.cli "which companies had pedestrian incidents?"
# score against the competency-question golden set (answer-set F1)
python tools/eval_kgquery.py            # dev split
python tools/eval_kgquery.py --heldout  # final numbers only
```

The pieces, the same five-dimension story:

- **Validations** — the P3 twist: there is **no read-only credential**. Neo4j Community Edition has no role management, so the structural floor is the **read-access-mode transaction** — every graph touch in `app/kgquery` goes through `execute_query(routing_=READ)`, and the server rejects any write at runtime regardless of what the model emitted. On top: a **static validator** (`validate.py`, U14) that accepts exactly one statement, rejects write clauses (`CREATE`/`MERGE`/`DELETE`/`DETACH`/`SET`/`REMOVE`/`FOREACH`/`DROP`/`LOAD CSV`) with string literals stripped first, rejects `CALL` **wholesale** (procedures are where read-only guarantees leak), rejects backtick identifiers (the escape hatch around the token scan), checks every `:Label`/`:REL` token against the schema allow-list, and injects a `LIMIT`; then an **`EXPLAIN` dry-run** in read mode catches syntax with zero execution.
- **Prompts** — system prompt fixes the output contract (one read-only Cypher, no prose/fences), the vocabulary constraint (only schema labels/rels/patterns), the universal `name` property, and the refusal contract (`RETURN NULL LIMIT 0`).
- **Context** — a **graph card** (`graph_card.py`, U14) rendered from the frozen schema yaml with plain pyyaml (never importing ontology modules — the api stays free of the sidecar env): 29 node labels with typed properties, 41 relationship types, and all 120 connection patterns. The schema being small and enumerable is the whole point of the graph — the entire vocabulary fits in the prompt (~12.6K chars).
- **Self-validation loop** — `assemble → generate → validate → execute(READ) → repair` (`agent.py`, U15), bounded by `max_iterations` (3) + budget. Two P3-specific edges: **graph-unreachable is a first-class degrade** (`graph_available=false`, zero model calls, budget untouched — the graph is rebuildable-not-authoritative and never assumed live), and a valid-but-empty result gets one bounded reconsideration (wrong entity name? wrong direction?) before the empty answer is accepted.
- **Golden set** — `golden/kgquery/{dev,heldout}.jsonl` (U16) seeded directly from the schema's **18 competency questions** (12 dev / 6 held-out, plus 3 unanswerable rows expecting refusal), scored on **answer-set equivalence + row-set F1** against hand-written gold Cypher — both candidate and gold execute read-mode against the live graph and are compared by results, never by query text. Held-out refuses without `--heldout`; a test pins that every committed gold Cypher passes the real static gate.
- **Web delivery** — `POST /kgquery/ask` + `GET /kgquery/status` (`routes.py`, U17), a same-origin proxy (`/api/kgquery/ask`), and the `/kg` page ("Ask the graph"): question box, the Cypher the model wrote, the result table, the repair trace, the schema-card sidebar (labels / rel types / patterns), a **persistent "answers cover the extracted subgraph (n≈143)" banner**, and a friendly graph-down state. Its own durable budget (`budget.py`, `KGQUERY_DAILY_BUDGET_USD`, ledger `kgquery_spend`) with the per-call estimate **measured from the rendered graph card** rather than a copied constant — the KTD-5 caveat, third time, resolved differently.

## The SQL→Cypher transfer — what carried, what didn't

**Carried almost verbatim:** the graph shape (nodes and edges are line-for-line parallel to `nlsql/agent.py`), the injected `Protocol` seams (model + data, fakes for every test), the budget reserve/release around the paid call, the attempts trace, the refusal contract idea, LIMIT injection, EXPLAIN-before-execute, and the golden discipline (execution-result comparison, split hygiene, deterministic summaries).

**Changed shape:**

- **The safety floor moved from a credential to a transaction mode.** Postgres gave us a `SELECT`-only role — safety by *identity*. CE Neo4j has no roles, so safety is by *session semantics* (`routing_=READ`), which the server enforces per statement. The floor is equally hard but lives in the seam's code, so the contract "every execution path goes through read mode" is pinned by a test on the real seam with a stubbed driver.
- **No sqlglot equivalent.** SQL got an AST walk; for Cypher the validator is a keyword/token gate (string literals stripped, backticks refused) with EXPLAIN + the read-mode floor + a graph that simply lacks off-schema labels as the deeper layers. Less precise, honestly documented as such — defense-in-depth rather than a parser guarantee.
- **The allow-list flipped from generated to frozen.** P1's schema card is introspected from the live DB so it can't drift; P3's card comes from the *frozen* schema yaml, which is the stronger source here — the graph was built from that schema, and the frozen-schema discipline means it can't drift either.
- **Graph-down is a product state, not an error.** Postgres is assumed up (the site depends on it); the graph is a rebuildable projection, so unreachable is a rendered, tested degrade at every layer (agent result, both routes, the page banner) and never costs a model call.

## Infrastructure decision (2026-07-02): Neo4j CE on Railway

Replaces the AuraDB Free assumption. Aura Free's 72h idle pause / eventual deletion was the worst operational risk for a learning project touched in bursts; a small always-on CE container (~512M heap + volume, ~$2–5/mo) on the same platform as everything else removes it. The `api` reaches it over Railway's private network; local dev uses the public TCP proxy (unencrypted bolt + strong password — accepted for a rebuildable graph of public NHTSA data; toggle the proxy off between sessions). `ontology/graph_load.py` needed **zero code changes** — it reads `NEO4J_URI`/`NEO4J_USERNAME`/`NEO4J_PASSWORD` as-is. Coverage honesty: the graph holds the ~143-incident extraction subgraph, so `/kg` answers will disagree with `/nlsql` counts — hence the persistent banner instead of pretending parity.

## Golden numbers

*Pending the Railway Neo4j provisioning (the U13 human step) — the harness is ready but needs the live graph.* Once the graph is up:

```bash
python tools/eval_kgquery.py   # writes tools/results/kgquery-eval-dev.{json,md}
```

Record the dev numbers here (accuracy, mean answer-set F1, refusal precision, mean iterations), and sanity-check the hand-written gold Cypher against the loaded subgraph first (`golden/kgquery/README.md` has the caveat: it was authored from the schema before the graph existed, so value spellings may need adjusting).

## What's deferred

- **U13 console steps** — provisioning the Railway Neo4j CE service, copying the extraction artifacts from the `avird-2026-ontology-v001` checkout, and rebuilding the graph. Documented in `docs/conventions/stack.md` ("Knowledge-graph queries") and `ontology/CLAUDE.md`.
- **P4 (router) and P5 (hybrid)** stay directional in the plan until P3 is live and the golden numbers exist.
