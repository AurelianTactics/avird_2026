// Typed server-side client for the internal `apps/api` service.
//
// Reads `API_URL` at request time (Railway reference var — see
// docs/conventions/stack.md). Server-only: `API_URL` carries no NEXT_PUBLIC_
// prefix and must never reach client code. Every call returns an `ApiResult`
// so pages degrade gracefully instead of throwing — mirrors the ok/error
// idiom the P0 placeholder index used.

// 127.0.0.1, not localhost: Node's fetch resolves localhost to ::1 first on
// Windows, and uvicorn binds IPv4 only — localhost silently ECONNREFUSEDs.
const API_URL = process.env.API_URL ?? "http://127.0.0.1:8000";

export type IncidentListItem = {
  report_id: string;
  reporting_entity: string | null;
  incident_date: string | null;
  city: string | null;
  state: string | null;
  severity: string | null; // RAW severity string — not a normalized bucket.
  crash_with: string | null;
};

export type IncidentList = {
  items: IncidentListItem[];
  page: number;
  page_size: number;
  total: number;
};

export type IncidentDetail = {
  report_id: string | null;
  reporting_entity: string | null;
  operating_entity: string | null;
  incident_date: string | null;
  incident_time: string | null;
  city: string | null;
  state: string | null;
  roadway_type: string | null;
  roadway_description: string | null;
  crash_with: string | null;
  severity: string | null;
  property_damage: string | null;
  cp_pre_crash_movement: string | null;
  sv_pre_crash_movement: string | null;
  cp_airbags_deployed: string | null;
  sv_airbags_deployed: string | null;
  cp_vehicle_towed: string | null;
  sv_vehicle_towed: string | null;
  passengers_belted: string | null;
  precrash_speed: string | null;
  law_enforcement_investigating: string | null;
  cp_contact_areas: string[];
  sv_contact_areas: string[];
  narrative: string | null;
  // Other reports of the same incident (shared raw "Same Incident ID").
  other_reports: { report_id: string; reporting_entity: string | null }[];
};

export type EntitySeverityGroupings = {
  buckets: string[];
  rows: { entity: string; counts: Record<string, number>; total: number }[];
};

// Derived heatmap views (W5). A matrix carries its two ordered axes plus the
// non-zero cells, so the client can render a grid and re-bucket cells (coarse
// contact-area grouping) without a second round trip.
export type HeatmapCell = { sv: string; cp: string; count: number };

export type HeatmapMatrix = {
  sv_axis: string[];
  cp_axis: string[];
  cells: HeatmapCell[];
};

// Resolved filter dimensions only (entity / state / severity), echoed back.
export type DerivedFilter = Record<string, string>;

export type Heatmaps = {
  contact_areas: HeatmapMatrix;
  pre_crash: HeatmapMatrix;
  applied_filter: DerivedFilter;
};

// Same heatmap shape as the default plus the NL-agent metadata.
export type HeatmapQueryResult = Heatmaps & {
  fallback: boolean;
  message: string;
};

export type RedactionRow = {
  entity: string;
  redacted: number;
  total: number;
  share: number;
};

export type RedactionStats = {
  redaction: RedactionRow[];
};

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: "unreachable" | "notfound" };

async function getJson<T>(path: string): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
    if (res.status === 404) return { ok: false, error: "notfound" };
    if (!res.ok) return { ok: false, error: "unreachable" };
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch {
    return { ok: false, error: "unreachable" };
  }
}

export type SortKey = "date" | "entity" | "severity";
export type SortDir = "asc" | "desc";

export function fetchIncidents(params: {
  page: number;
  sort: SortKey;
  dir: SortDir;
}): Promise<ApiResult<IncidentList>> {
  const qs = new URLSearchParams({
    page: String(params.page),
    sort: params.sort,
    dir: params.dir,
  });
  return getJson<IncidentList>(`/incidents?${qs.toString()}`);
}

export function fetchIncident(
  reportId: string,
): Promise<ApiResult<IncidentDetail>> {
  return getJson<IncidentDetail>(`/incidents/${encodeURIComponent(reportId)}`);
}

export function fetchEntitySeverity(): Promise<
  ApiResult<EntitySeverityGroupings>
> {
  return getJson<EntitySeverityGroupings>("/groupings/entity-severity");
}

// Default (unfiltered) heatmaps for the /heatmaps server render.
export function fetchHeatmaps(): Promise<ApiResult<Heatmaps>> {
  return getJson<Heatmaps>("/derived/heatmaps");
}

// Static redaction breakdown for the /groupings table (unfiltered, KTD 9).
export function fetchRedactionStats(): Promise<ApiResult<RedactionStats>> {
  return getJson<RedactionStats>("/derived/redaction");
}
