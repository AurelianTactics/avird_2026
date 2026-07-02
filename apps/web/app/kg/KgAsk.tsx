"use client";

import { useState } from "react";
import type { KgResult } from "../lib/api";

// Client shell for the graph-query box: posts the question to the same-origin
// proxy (/api/kgquery/ask), then shows the Cypher the model wrote, the result
// table, and the repair trace when the loop fired. Two degrade states render
// as notices — an ordinary fallback (couldn't answer) and a down graph
// (graph_available=false) — the page never breaks on a bad question.

const EXAMPLES = [
  "Which companies were involved in the most incidents?",
  "Which companies had pedestrian-related incidents?",
  "What pre-crash maneuvers most often preceded a collision?",
  "In which cities and states do incidents occur most frequently?",
];

function ResultTable({ rows }: { rows: Record<string, unknown>[] }) {
  if (rows.length === 0) return <p className="muted">No rows returned.</p>;
  const columns = Object.keys(rows[0]);
  return (
    <div className="nlsql-table-wrap">
      <table className="nlsql-table">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.slice(0, 200).map((row, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c}>{String(row[c] ?? "")}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 200 ? (
        <p className="muted">Showing the first 200 of {rows.length} rows.</p>
      ) : null}
    </div>
  );
}

export default function KgAsk() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<KgResult | null>(null);

  async function run(q: string) {
    setLoading(true);
    try {
      const res = await fetch("/api/kgquery/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      setResult((await res.json()) as KgResult);
    } catch {
      setResult({
        question: q,
        cypher: null,
        rows: [],
        row_count: 0,
        iterations: 0,
        fallback: true,
        attempts: [],
        message: "Couldn't run that question — please try again.",
        graph_available: true,
      });
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (question.trim()) run(question.trim());
  }

  // The repair loop is worth showing: a rejected first attempt then a valid one.
  const showTrace =
    result &&
    (result.iterations > 1 ||
      result.attempts.some((a) => a.status === "invalid"));

  return (
    <div className="nlsql">
      <form className="query" onSubmit={onSubmit}>
        <label className="query__label" htmlFor="kg-q">
          Ask a question about the incident graph
        </label>
        <div className="query__row">
          <input
            id="kg-q"
            className="query__input"
            type="text"
            value={question}
            maxLength={500}
            placeholder="e.g. which companies were involved in the most incidents?"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button className="query__submit" type="submit" disabled={loading}>
            {loading ? "Thinking…" : "Ask"}
          </button>
        </div>
      </form>

      <p className="nlsql-examples">
        Try:{" "}
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            type="button"
            className="chip chip--button"
            onClick={() => {
              setQuestion(ex);
              run(ex);
            }}
          >
            {ex}
          </button>
        ))}
      </p>

      <div aria-live="polite">
        {result && !result.graph_available ? (
          <p className="notice">
            The knowledge graph is unreachable right now — the rest of the site
            still works, and this page recovers as soon as the graph is back.
          </p>
        ) : null}

        {result && result.graph_available && result.fallback ? (
          <p className="notice notice--subtle">
            {result.message || "Couldn't answer that from the graph."}
            {result.cypher ? (
              <>
                {" "}
                Last attempted Cypher: <code>{result.cypher}</code>
              </>
            ) : null}
          </p>
        ) : null}

        {result && !result.fallback ? (
          <div className="nlsql-result">
            <h2 className="nlsql-result__h">Cypher the model wrote</h2>
            <pre className="nlsql-sql">{result.cypher}</pre>

            {showTrace ? (
              <details className="nlsql-trace">
                <summary>
                  Repair trace — {result.iterations} attempt
                  {result.iterations === 1 ? "" : "s"}
                </summary>
                <ol>
                  {result.attempts.map((a) => (
                    <li key={a.iteration}>
                      <span className={`tag tag--${a.status}`}>{a.status}</span>
                      <code>{a.cypher}</code>
                      {a.reason ? (
                        <span className="muted"> — {a.reason}</span>
                      ) : null}
                    </li>
                  ))}
                </ol>
              </details>
            ) : null}

            <h2 className="nlsql-result__h">
              Result ({result.row_count} rows)
            </h2>
            <ResultTable rows={result.rows} />
          </div>
        ) : null}
      </div>
    </div>
  );
}
