import Link from "next/link";
import { fetchIncidents, type SortDir, type SortKey } from "./lib/api";

// Reads API_URL at request time — must run dynamically (Railway reference var).
export const dynamic = "force-dynamic";

const SORT_KEYS: SortKey[] = ["date", "entity", "severity"];
const DIRS: SortDir[] = ["asc", "desc"];
const DEFAULT_SORT: SortKey = "date";
const DEFAULT_DIR: SortDir = "desc";

type SearchParams = Record<string, string | string[] | undefined>;

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function parseParams(sp: SearchParams): {
  page: number;
  sort: SortKey;
  dir: SortDir;
} {
  const rawPage = Number(first(sp.page));
  const page =
    Number.isFinite(rawPage) && rawPage >= 1 ? Math.floor(rawPage) : 1;
  const sortRaw = first(sp.sort) as SortKey | undefined;
  const dirRaw = first(sp.dir) as SortDir | undefined;
  return {
    page,
    sort: sortRaw && SORT_KEYS.includes(sortRaw) ? sortRaw : DEFAULT_SORT,
    dir: dirRaw && DIRS.includes(dirRaw) ? dirRaw : DEFAULT_DIR,
  };
}

function sortHref(
  col: SortKey,
  current: { sort: SortKey; dir: SortDir },
): string {
  // Clicking the active column flips direction; a fresh column starts ascending.
  // Changing sort resets to page 1.
  const dir: SortDir =
    current.sort === col && current.dir === "asc" ? "desc" : "asc";
  return `/?sort=${col}&dir=${dir}&page=1`;
}

function ariaSort(
  col: SortKey,
  current: { sort: SortKey; dir: SortDir },
): "ascending" | "descending" | undefined {
  if (current.sort !== col) return undefined;
  return current.dir === "asc" ? "ascending" : "descending";
}

const COLUMNS: { key: SortKey; label: string }[] = [
  { key: "entity", label: "Reporting Entity" },
  { key: "date", label: "Incident Date" },
  { key: "severity", label: "Highest Injury Severity Alleged" },
];

export default async function IncidentsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const current = parseParams(await searchParams);
  const result = await fetchIncidents(current);

  return (
    <main>
      <h1>Incidents</h1>
      <p className="muted">
        Raw NHTSA SGO crash reports — every reported row, newest first. Sort by
        clicking a column header. Dates are raw report text, so
        &ldquo;recent-first&rdquo; is approximate.
      </p>

      {!result.ok ? (
        <p className="notice">
          Could not load incidents. The data service may be unavailable.
        </p>
      ) : result.data.items.length === 0 ? (
        <p className="notice">No incidents found.</p>
      ) : (
        <>
          <table className="data-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} aria-sort={ariaSort(c.key, current)}>
                    <Link className="sort-link" href={sortHref(c.key, current)}>
                      {c.label}
                    </Link>
                  </th>
                ))}
                <th>City</th>
                <th>State</th>
                <th>Crash With</th>
              </tr>
            </thead>
            <tbody>
              {result.data.items.map((row) => (
                <tr key={row.report_id}>
                  <td>{row.reporting_entity ?? "—"}</td>
                  <td>
                    <Link
                      href={`/incidents/${encodeURIComponent(row.report_id)}`}
                    >
                      {row.incident_date ?? row.report_id}
                    </Link>
                  </td>
                  <td>{row.severity ?? "—"}</td>
                  <td>{row.city ?? "—"}</td>
                  <td>{row.state ?? "—"}</td>
                  <td>{row.crash_with ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pagination
            page={result.data.page}
            pageSize={result.data.page_size}
            total={result.data.total}
            sort={current.sort}
            dir={current.dir}
          />
        </>
      )}
    </main>
  );
}

function Pagination({
  page,
  pageSize,
  total,
  sort,
  dir,
}: {
  page: number;
  pageSize: number;
  total: number;
  sort: SortKey;
  dir: SortDir;
}) {
  const lastPage = Math.max(1, Math.ceil(total / pageSize));
  const hasPrev = page > 1;
  const hasNext = page < lastPage;
  const href = (p: number) => `/?sort=${sort}&dir=${dir}&page=${p}`;

  return (
    <div className="pager">
      {hasPrev ? (
        <Link href={href(page - 1)}>← Prev</Link>
      ) : (
        <span className="muted">← Prev</span>
      )}
      <span className="muted">
        Page {page} of {lastPage} · {total} reports
      </span>
      {hasNext ? (
        <Link href={href(page + 1)}>Next →</Link>
      ) : (
        <span className="muted">Next →</span>
      )}
    </div>
  );
}
