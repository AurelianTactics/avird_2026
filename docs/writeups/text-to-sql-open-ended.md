# Open-ended text-to-SQL (agentic data-access P1)

The first phase of the [agentic data-access progression](../plans/2026-06-30-001-feat-agentic-data-access-progression-plan.md). It graduates from the bounded NL filter (`app/derived/agent.py`, which maps free text to an allow-listed entity/state/severity filter) to a model that **authors real `SELECT` SQL** over the whole `treated_incident_reports` table.

## What shipped

A text-to-SQL agent (`app/nlsql/`), local-first with a web surface layered on after the live-exposure gate:

```bash
# one-time: provision the SELECT-only role on the seeded local DB
python tools/setup_readonly_role.py
# ask a question (uses the real model when ANTHROPIC_API_KEY is set, else a stub)
python -m app.nlsql.cli "which five companies have the most fatal incidents?"
# score against the golden set (execution-result equivalence)
python tools/eval_nlsql.py            # dev split
python tools/eval_nlsql.py --heldout  # final numbers only
```

The pieces, each the same five-dimension story the plan defines once:

- **Validations** — three layers, cheapest-first, fail-closed. A Postgres **read-only role** (`db/roles/readonly_role.sql`, U1) is the structural floor: it has `SELECT` on the one treated table and *nothing else*, so even a perfect injection can't mutate or read another table. On top, a **static validator** (`validate.py`, U3) parses with `sqlglot`, accepts exactly one read-only query, rejects DML/DDL/`;`-chaining/CTE-wrapped-DML/`SELECT INTO`/`pg_*`/`information_schema`/unlisted tables and system function calls (`pg_*`, `set_config` — which could otherwise disable the role's `statement_timeout` on a pooled session), and injects a `LIMIT`. Then an **`EXPLAIN` dry-run** catches column typos with zero rows touched.
- **Prompts** — a system prompt fixing the dialect (Postgres), the output contract (one `SELECT`, no prose/fences), the column-naming trap, and the refusal contract (`SELECT NULL WHERE false`).
- **Context** — a **schema card** (`schema_card.py`, U2) generated from `information_schema` + `SELECT DISTINCT` value samples, so the grounding can't drift from the real table.
- **Self-validation loop** — `generate → validate → execute → repair` (`agent.py`, U4): on a validation failure, DB error, or implausible empty result, the observation is fed back and the model repairs, bounded by `max_iterations` (3) and the budget guard.
- **Golden set** — `golden/nlsql/{dev,heldout}.jsonl` scored on **execution-result equivalence** (`eval_nlsql.py`, U6), not SQL string match — the honest measure.
- **Web delivery (the live-exposure gate, passed)** — `POST /nlsql/query` + `GET /nlsql/schema` (`nlsql/routes.py`), a same-origin `web` proxy (`/api/nlsql/query`), and the `/nlsql` page ("Ask the data"): question box, the SQL the model wrote, the result table, the repair trace when it fired, and the live column dictionary. Gated by its own durable daily budget (`nlsql/budget.py`, `NLSQL_DAILY_BUDGET_USD`, ledger `nlsql_spend`) with a per-call estimate sized to the P1 prompt — the KTD-5 caveat, resolved. The route never 500s; failures come back as `fallback=true`.

## Why these choices

- **Read-only role over a bigger allow-list (KTD-1).** A bounded filter has to anticipate every query shape; a read-only role lets the model author *any* `SELECT` and still be safe by construction. The validator is defense-in-depth, not the only line — which is why the column allow-list is deliberately best-effort (column existence is `EXPLAIN`'s job) while the *table* allow-list and statement-type gate are hard.
- **Result-set equivalence over SQL match.** Two correct queries can read completely differently; comparing what they *return* (order-insensitive, floats rounded) is the only measure that doesn't punish stylistic variation or reward a query that looks right but counts wrong.
- **Everything injected behind a `Protocol`.** The model (`SqlModel`) and the data layer (`SqlData`) are seams with fakes, so the whole loop — including the repair and fallback edges — is unit-tested with no key, no network, no Postgres, mirroring `derived/agent.py`.

## What surprised / sharp edges

- **The column-naming trap is real and worth a dedicated prompt section.** The treated table mixes cleaned snake_case columns (`master_entity`, `incident_date`) with raw passthrough columns that must be double-quoted exactly (`"Highest Injury Severity Alleged"`). A model that quotes the wrong one writes SQL that fails at `EXPLAIN` — so the schema card spells the distinction out and renders each identifier the way SQL needs it.
- **`sqlglot` makes the read-only shape check robust** where regex would not: `WITH x AS (DELETE … RETURNING *) SELECT * FROM x` and `SELECT … INTO foo` both *look* like reads but are caught by walking the AST for any write node. CTE aliases are excluded from the table allow-list so legitimate `WITH` clauses aren't mistaken for unknown tables.
- **Empty results need a bounded reconsider, not a fallback.** A valid query returning zero rows is often a wrong filter *value*, so the loop reconsiders once (feeding that hint back) and then accepts the empty answer rather than looping.

## What's deferred

- **Production wiring.** The route is built and budget-guarded, but the prod side of the gate — provisioning the read-only role on Railway and setting `READONLY_DATABASE_URL` on the `api` service — happens at deploy time (`db/roles/readonly_role.sql` + `docs/conventions/stack.md`).
- **Golden numbers.** The harness produces a committed JSON+markdown summary under `tools/results/` when run against a seeded DB with a key. The gold SQL is a starting seed; category-string filters (e.g. exact raw severity values) should be tuned against the seeded DB using the CLI's `--verbose` value samples before the held-out numbers are trusted.
- **Few-shot exemplars in the live prompt.** The agent accepts `examples=` (drawn from the dev split, never held-out) but the route doesn't wire them yet — a cheap accuracy lever once the golden numbers show where the model stumbles.
