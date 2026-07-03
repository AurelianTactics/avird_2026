"use client";

import { useState } from "react";
import ResultTable from "../components/ResultTable";
import type { NlSqlResult } from "../lib/api";

// Client shell for the text-to-SQL box: posts the question to the same-origin
// proxy (/api/nlsql/query), then shows the SQL the model wrote, the result table,
// and the repair trace when the loop fired. A fallback (couldn't answer / service
// down) renders as a subtle note — the page never breaks on a bad question.

const EXAMPLES = [
  "How many incidents did Waymo report?",
  "Which five companies have the most incidents?",
  "How many incidents occurred in each state?",
  "How many fatal incidents are there?",
];

export default function NlSqlQuery() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<NlSqlResult | null>(null);

  async function run(q: string) {
    setLoading(true);
    try {
      const res = await fetch("/api/nlsql/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      // A non-2xx body (e.g. the proxy's 422) isn't NlSqlResult-shaped — treat
      // it as a fallback rather than crashing the render on a missing field.
      if (!res.ok) throw new Error(`upstream ${res.status}`);
      setResult((await res.json()) as NlSqlResult);
    } catch {
      setResult({
        question: q,
        sql: null,
        rows: [],
        row_count: 0,
        iterations: 0,
        fallback: true,
        attempts: [],
        message: "Couldn't run that question — please try again.",
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
        <label className="query__label" htmlFor="nlsql-q">
          Ask a question about the crash data
        </label>
        <div className="query__row">
          <input
            id="nlsql-q"
            className="query__input"
            type="text"
            value={question}
            maxLength={500}
            placeholder="e.g. which five companies have the most incidents?"
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
        {result && result.fallback ? (
          <p className="notice notice--subtle">
            {result.message || "Couldn't answer that from the data."}
            {result.sql ? (
              <>
                {" "}
                Last attempted SQL: <code>{result.sql}</code>
              </>
            ) : null}
          </p>
        ) : null}

        {result && !result.fallback ? (
          <div className="nlsql-result">
            <h2 className="nlsql-result__h">SQL the model wrote</h2>
            <pre className="nlsql-sql">{result.sql}</pre>

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
                      <code>{a.sql}</code>
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
