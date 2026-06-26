import { fetchEntitySeverity, fetchRedactionStats } from "../lib/api";
import RedactionStats from "./RedactionStats";

export const dynamic = "force-dynamic";

export default async function GroupingsPage() {
  const result = await fetchEntitySeverity();
  const redaction = await fetchRedactionStats();

  return (
    <main>
      <h1>Groupings</h1>
      <p className="muted">
        Canonical (deduplicated) crash counts by reporting entity and highest
        injury severity. Severity is normalized into seven buckets; columns run
        left-to-right by decreasing harm.
      </p>

      {!result.ok ? (
        <p className="notice">
          Could not load groupings. The data service may be unavailable.
        </p>
      ) : result.data.rows.length === 0 ? (
        <p className="notice">No grouping data available.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Entity</th>
              {result.data.buckets.map((b) => (
                <th key={b} className="num">
                  {b}
                </th>
              ))}
              <th className="num">Total</th>
            </tr>
          </thead>
          <tbody>
            {result.data.rows.map((row) => (
              <tr key={row.entity}>
                <td>{row.entity}</td>
                {result.data.buckets.map((b) => {
                  const n = row.counts[b] ?? 0;
                  return (
                    <td key={b} className={n === 0 ? "num zero" : "num"}>
                      {n}
                    </td>
                  );
                })}
                <td className="num">{row.total}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <RedactionStats result={redaction} />
    </main>
  );
}
