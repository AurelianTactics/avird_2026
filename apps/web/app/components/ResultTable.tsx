// Generic row-table renderer shared by the "show your work" query pages
// (/nlsql SQL results, /kg Cypher results). Pure presentation: takes whatever
// rows the agent returned and renders a capped table — no per-phase state.

export default function ResultTable({
  rows,
}: {
  rows: Record<string, unknown>[];
}) {
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
