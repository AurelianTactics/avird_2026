import { fetchNlSqlSchema } from "../lib/api";
import NlSqlQuery from "./NlSqlQuery";

// Reads API_URL at request time — must run dynamically (Railway reference var).
export const dynamic = "force-dynamic";

export default async function NlSqlPage() {
  const schema = await fetchNlSqlSchema();
  const dict = schema.ok && schema.data.available ? schema.data : null;

  return (
    <main>
      <h1>Ask the data</h1>
      <p className="muted">
        Type a question in plain English and a language model (Claude) writes a
        real SQL query against the crash-incident table, runs it, and shows you
        both the query and the answer. If its first query fails to validate or
        run, it sees the error and repairs — you can watch that in the repair
        trace. The query runs as a <strong>read-only</strong> database role, so it
        can only ever read this one table.
      </p>

      <NlSqlQuery />

      <section className="nlsql-dict">
        <h2>What you can ask about — the columns</h2>
        {dict ? (
          <>
            <p className="muted">
              The model is grounded on the <code>{dict.table}</code> table. These
              are its columns; low-cardinality ones list their real values so you
              can filter on them.
            </p>
            <details>
              <summary>{dict.columns.length} columns</summary>
              <table className="nlsql-table">
                <thead>
                  <tr>
                    <th>Column</th>
                    <th>Type</th>
                    <th>Known values</th>
                  </tr>
                </thead>
                <tbody>
                  {dict.columns.map((c) => (
                    <tr key={c.name}>
                      <td>
                        <code>{c.identifier}</code>
                      </td>
                      <td>{c.type}</td>
                      <td>
                        {dict.value_samples[c.name]
                          ? dict.value_samples[c.name].join(", ")
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          </>
        ) : (
          <p className="notice">
            The column dictionary is unavailable right now (the read-only database
            role may not be reachable). You can still ask questions — the model is
            grounded on the live schema server-side.
          </p>
        )}
      </section>
    </main>
  );
}
