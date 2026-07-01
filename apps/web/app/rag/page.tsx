import { fetchRagStatus } from "../lib/api";
import RagAsk from "./RagAsk";

// Reads API_URL at request time — must run dynamically (Railway reference var).
export const dynamic = "force-dynamic";

export default async function RagPage() {
  const status = await fetchRagStatus();
  const ready = status.ok && status.data.available ? status.data : null;

  return (
    <main>
      <h1>Ask the narratives</h1>
      <p className="muted">
        Every crash report includes a written narrative of what happened. Ask a
        question in plain English and the system retrieves the most similar
        crash narratives by meaning (cosine similarity over narrative
        embeddings), then a language model (Claude) answers{" "}
        <strong>only from those narratives</strong>, citing the incidents it
        used. A citation gate blocks made-up citations, and a second model
        judges whether every claim is actually supported — you can see both the
        answer and the narratives it read.
      </p>

      {ready ? (
        <p className="muted">
          <strong>{ready.corpus_size.toLocaleString()}</strong> narratives
          indexed and searchable.
        </p>
      ) : (
        <p className="notice">
          The narrative index is unavailable right now (the embedding store may
          not be reachable or ingested). Questions will return a service notice
          instead of answers.
        </p>
      )}

      <RagAsk />
    </main>
  );
}
