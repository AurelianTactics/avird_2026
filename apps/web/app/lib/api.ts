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

// Shared secret for the internal web→api hop. Server-only; sent only when set
// (production). Mirrors apps/web/app/lib/debate.ts so read + write paths agree.
function internalSecretHeaders(): Record<string, string> {
  const secret = process.env.API_SHARED_SECRET;
  return secret ? { "x-internal-secret": secret } : {};
}

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

// Precomputed LLM "insurance adjuster" verdict for one report. A parse-failure
// sentinel row carries null verdict + null percentage + an error explanation.
export type FaultVerdict = {
  report_id: string | null;
  fault_version: string | null;
  is_av_at_fault: boolean | null;
  av_fault_percentage: number | null; // 0..1
  short_explanation: string | null;
  model: string | null;
  created_at: string | null;
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

// --- Text-to-SQL (P1) -------------------------------------------------------

// One column from the data dictionary the /nlsql page shows next to the box.
export type NlSqlColumn = {
  name: string;
  type: string;
  raw: boolean; // true => mixed-case raw column that must be double-quoted
  identifier: string; // the column rendered the way SQL needs it
};

export type NlSqlSchema = {
  available: boolean;
  table: string | null;
  columns: NlSqlColumn[];
  value_samples: Record<string, string[]>;
};

// One author attempt in the repair trace.
export type NlSqlAttempt = {
  iteration: number;
  sql: string | null;
  status: string; // "valid" | "invalid"
  reason: string;
};

// The result the /nlsql page renders (SQL + rows + repair trace).
export type NlSqlResult = {
  question: string;
  sql: string | null;
  rows: Record<string, unknown>[];
  row_count: number;
  iterations: number;
  fallback: boolean;
  attempts: NlSqlAttempt[];
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
    const res = await fetch(`${API_URL}${path}`, {
      cache: "no-store",
      headers: internalSecretHeaders(),
    });
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

export function fetchFault(reportId: string): Promise<ApiResult<FaultVerdict>> {
  return getJson<FaultVerdict>(
    `/incidents/${encodeURIComponent(reportId)}/fault`,
  );
}

// Default (unfiltered) heatmaps for the /heatmaps server render.
export function fetchHeatmaps(): Promise<ApiResult<Heatmaps>> {
  return getJson<Heatmaps>("/derived/heatmaps");
}

// Static redaction breakdown for the /groupings table (unfiltered, KTD 9).
export function fetchRedactionStats(): Promise<ApiResult<RedactionStats>> {
  return getJson<RedactionStats>("/derived/redaction");
}

// Column data-dictionary for the /nlsql page (server-rendered next to the box).
export function fetchNlSqlSchema(): Promise<ApiResult<NlSqlSchema>> {
  return getJson<NlSqlSchema>("/nlsql/schema");
}

// --- Narrative RAG (P2) ------------------------------------------------------

// One retrieved narrative with provenance — "what the model read".
export type RagChunk = {
  incident_id: string;
  narrative: string;
  distance: number;
};

// The result the /rag page renders (cited answer + retrieved narratives).
export type RagResult = {
  question: string;
  answer: string;
  cited_incident_ids: string[];
  retrieved_ids: string[];
  retrieved: RagChunk[];
  supported: boolean;
  refused: boolean;
  iterations: number;
  fallback: boolean;
  message: string;
};

// Store reachability + corpus size for the /rag page (server-rendered).
export type RagStatus = {
  available: boolean;
  corpus_size: number;
};

export function fetchRagStatus(): Promise<ApiResult<RagStatus>> {
  return getJson<RagStatus>("/rag/status");
}

// --- Knowledge-graph queries (P3) ---------------------------------------------

// One author attempt in the Cypher repair trace.
export type KgAttempt = {
  iteration: number;
  cypher: string | null;
  status: string; // "valid" | "invalid"
  reason: string;
};

// The result the /kg page renders (Cypher + rows + repair trace).
// graph_available=false means the Neo4j instance was unreachable — a
// first-class degrade state, distinct from an ordinary fallback.
export type KgResult = {
  question: string;
  cypher: string | null;
  rows: Record<string, unknown>[];
  row_count: number;
  iterations: number;
  fallback: boolean;
  attempts: KgAttempt[];
  message: string;
  graph_available: boolean;
};

// Graph reachability + counts + the schema card for the /kg sidebar.
export type KgStatus = {
  available: boolean;
  nodes: number;
  relationships: number;
  card: {
    labels: string[];
    relationship_types: string[];
    patterns: string[][]; // [source, relationship, target]
  };
};

export function fetchKgStatus(): Promise<ApiResult<KgStatus>> {
  return getJson<KgStatus>("/kgquery/status");
}
