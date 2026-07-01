"use client";

import { useState } from "react";
import type { RagResult } from "../lib/api";

// Client shell for the narrative-RAG box: posts the question to the same-origin
// proxy (/api/rag/ask), then shows the cited answer, the incidents it cited, and
// the retrieved narratives the model read. A fallback (couldn't answer / service
// down) renders as a subtle note — the page never breaks on a bad question.

const EXAMPLES = [
  "What happens when AVs encounter pedestrians?",
  "Describe rear-end collisions while stopped at a light",
  "What do the narratives say about cyclists?",
  "How do incidents at intersections unfold?",
];

function fallbackResult(question: string): RagResult {
  return {
    question,
    answer: "",
    cited_incident_ids: [],
    retrieved_ids: [],
    retrieved: [],
    supported: false,
    refused: false,
    iterations: 0,
    fallback: true,
    message: "Couldn't run that question — please try again.",
  };
}

export default function RagAsk() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RagResult | null>(null);

  async function run(q: string) {
    setLoading(true);
    try {
      const res = await fetch("/api/rag/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      setResult((await res.json()) as RagResult);
    } catch {
      setResult(fallbackResult(q));
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (question.trim()) run(question.trim());
  }

  return (
    <div className="rag">
      <form className="query" onSubmit={onSubmit}>
        <label className="query__label" htmlFor="rag-q">
          Ask about the crash narratives
        </label>
        <div className="query__row">
          <input
            id="rag-q"
            className="query__input"
            type="text"
            value={question}
            maxLength={500}
            placeholder="e.g. what happens when AVs encounter pedestrians at night?"
            onChange={(e) => setQuestion(e.target.value)}
          />
          <button className="query__submit" type="submit" disabled={loading}>
            {loading ? "Searching…" : "Ask"}
          </button>
        </div>
      </form>

      <p className="rag-examples">
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
          <div className="notice notice--subtle">
            <p>
              {result.message || "Couldn't answer that from the narratives."}
            </p>
            {result.retrieved.length > 0 ? (
              <p className="muted">
                Most relevant incidents:{" "}
                {result.retrieved_ids.map((id) => (
                  <code key={id} className="rag-id">
                    {id}
                  </code>
                ))}
              </p>
            ) : null}
          </div>
        ) : null}

        {result && !result.fallback && result.refused ? (
          <p className="notice notice--subtle">
            The retrieved narratives don&apos;t support an answer to that — the
            model refused rather than guessing. Try a question about what
            happens in the crash reports.
          </p>
        ) : null}

        {result && !result.fallback && !result.refused ? (
          <div className="rag-result">
            <h2 className="rag-result__h">
              Answer{" "}
              <span
                className={`tag ${result.supported ? "tag--valid" : "tag--invalid"}`}
              >
                {result.supported ? "faithful" : "unverified"}
              </span>
            </h2>
            <p className="rag-answer">{result.answer}</p>

            <p className="muted">
              Cited incidents:{" "}
              {result.cited_incident_ids.length > 0
                ? result.cited_incident_ids.map((id) => (
                    <code key={id} className="rag-id">
                      {id}
                    </code>
                  ))
                : "none"}
              {result.iterations > 1
                ? ` — took ${result.iterations} attempts (the self-check loop fired)`
                : null}
            </p>

            <details className="rag-chunks">
              <summary>
                What the model read — {result.retrieved.length} retrieved
                narrative{result.retrieved.length === 1 ? "" : "s"}
              </summary>
              <ol>
                {result.retrieved.map((c, i) => (
                  <li key={`${c.incident_id}-${i}`}>
                    <p className="rag-chunk__meta">
                      [{i + 1}] incident <code>{c.incident_id}</code>{" "}
                      <span className="muted">
                        (distance {c.distance.toFixed(3)})
                      </span>
                    </p>
                    <p className="rag-chunk__text">{c.narrative}</p>
                  </li>
                ))}
              </ol>
            </details>
          </div>
        ) : null}
      </div>
    </div>
  );
}
