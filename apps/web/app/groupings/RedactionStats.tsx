import type {
  ApiResult,
  RedactionStats as RedactionStatsData,
} from "../lib/api";

// Static redacted-narrative stats (R14), rendered at the bottom of /groupings.
// Plain server-rendered table — outside the NL query surface (plan KTD 9): it is
// grouped by entity, so a marquee entity filter would collapse it to one row.
export default function RedactionStats({
  result,
}: {
  result: ApiResult<RedactionStatsData>;
}) {
  const rows = result.ok
    ? [...(result.data.redaction ?? [])].sort((a, b) => b.share - a.share)
    : [];

  return (
    <section>
      <h2>Narrative redaction</h2>
      <p className="muted">
        Share of crash narratives that contain an SGO redaction marker
        (&ldquo;[redacted]&rdquo;, &ldquo;CBI&rdquo;,
        &ldquo;confidential&rdquo;), by reporting entity. A higher share means
        more of that entity&rsquo;s narratives were withheld.
      </p>

      {!result.ok ? (
        <p className="notice">
          Could not load redaction stats. The data service may be unavailable.
        </p>
      ) : rows.length === 0 ? (
        <p className="notice">No redaction data available.</p>
      ) : (
        <table className="data-table">
          <thead>
            <tr>
              <th>Entity</th>
              <th className="num">Redacted</th>
              <th className="num">Total</th>
              <th className="num">% redacted</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const pct = (row.share * 100).toFixed(1);
              return (
                <tr key={row.entity ?? "—"}>
                  <td>{row.entity ?? "Unknown"}</td>
                  <td className={row.redacted === 0 ? "num zero" : "num"}>
                    {row.redacted}
                  </td>
                  <td className="num">{row.total}</td>
                  <td className={row.share === 0 ? "num zero" : "num"}>
                    {pct}%
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </section>
  );
}
