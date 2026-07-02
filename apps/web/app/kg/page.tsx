import { fetchKgStatus } from "../lib/api";
import KgAsk from "./KgAsk";

// Reads API_URL at request time — must run dynamically (Railway reference var).
export const dynamic = "force-dynamic";

export default async function KgPage() {
  const status = await fetchKgStatus();
  const kg = status.ok ? status.data : null;
  const card = kg?.card ?? null;

  return (
    <main>
      <h1>Ask the graph</h1>
      <p className="muted">
        Type a question in plain English and a language model (Claude) writes a
        real Cypher query against a knowledge graph of crash incidents, runs it,
        and shows you both the query and the answer. If its first query fails to
        validate or run, it sees the error and repairs — you can watch that in
        the repair trace. Every query executes in a <strong>read-only</strong>{" "}
        transaction, so it can only ever read the graph.
      </p>

      <p className="notice">
        Answers cover the extracted subgraph (≈143 incidents from one extraction
        run), not the full dataset — counts here will differ from the{" "}
        <a href="/nlsql">Ask the data</a> page, which queries every incident.
      </p>

      {kg && !kg.available ? (
        <p className="notice">
          The knowledge graph is unreachable right now. You can still type a
          question — the page degrades gracefully — but answers need the graph
          to be up.
        </p>
      ) : null}

      <KgAsk />

      <section className="nlsql-dict">
        <h2>What you can ask about — the graph schema</h2>
        {card && card.labels.length > 0 ? (
          <>
            <p className="muted">
              The model is grounded on the frozen ontology schema
              {kg?.available ? (
                <>
                  {" "}
                  — the live graph holds <strong>{kg.nodes}</strong> nodes and{" "}
                  <strong>{kg.relationships}</strong> relationships
                </>
              ) : null}
              . These are its node labels, relationship types, and the
              connection patterns the graph actually contains.
            </p>
            <details>
              <summary>{card.labels.length} node labels</summary>
              <p>
                {card.labels.map((l) => (
                  <span key={l} className="chip">
                    {l}
                  </span>
                ))}
              </p>
            </details>
            <details>
              <summary>
                {card.relationship_types.length} relationship types
              </summary>
              <p>
                {card.relationship_types.map((r) => (
                  <span key={r} className="chip">
                    {r}
                  </span>
                ))}
              </p>
            </details>
            <details>
              <summary>{card.patterns.length} connection patterns</summary>
              <ul>
                {card.patterns.map((p, i) => (
                  <li key={i}>
                    <code>
                      ({p[0]})-[:{p[1]}]-&gt;({p[2]})
                    </code>
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : (
          <p className="notice">
            The schema card is unavailable right now. You can still ask
            questions — the model is grounded on the schema server-side.
          </p>
        )}
      </section>
    </main>
  );
}
