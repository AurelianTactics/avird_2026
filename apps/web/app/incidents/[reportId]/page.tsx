import Link from "next/link";
import {
  fetchFault,
  fetchIncident,
  type ApiResult,
  type FaultVerdict,
  type IncidentDetail,
} from "../../lib/api";
import DebatePanel from "./DebatePanel";
import IncidentTabs from "./IncidentTabs";
import { isTabId, type TabId } from "./tabs";

export const dynamic = "force-dynamic";

// Shown alongside both LLM features (R5a). The same real-world crash can get
// different verdicts across its separate reporting rows — that's expected.
const FAULT_DISCLAIMER =
  "This is an AI opinion generated for entertainment and learning — not a " +
  "legal or factual determination. The same real-world crash can receive " +
  "different verdicts across its separate reporting rows.";

function val(v: string | null | undefined): string {
  const s = (v ?? "").trim();
  return s === "" ? "—" : s;
}

function FaultBlock({ fault }: { fault: ApiResult<FaultVerdict> }) {
  return (
    <section className="fault-verdict">
      <h2>AI fault verdict</h2>
      <FaultBody fault={fault} />
      <p className="muted fault-disclaimer">{FAULT_DISCLAIMER}</p>
    </section>
  );
}

function FaultBody({ fault }: { fault: ApiResult<FaultVerdict> }) {
  if (!fault.ok) {
    // notfound = no verdict computed for this report yet (graceful empty state);
    // unreachable = the data service is down. Neither is an error on the page.
    return (
      <p className="notice">
        {fault.error === "notfound"
          ? "No AI fault verdict has been computed for this report yet."
          : "The fault verdict service is currently unavailable."}
      </p>
    );
  }

  const v = fault.data;
  if (v.is_av_at_fault === null) {
    // Parse-failure sentinel — never a guessed verdict.
    return (
      <p className="notice">
        The AI could not produce a usable verdict for this report.
      </p>
    );
  }

  const pct =
    v.av_fault_percentage === null
      ? null
      : Math.round(v.av_fault_percentage * 100);
  return (
    <>
      <dl className="detail-grid">
        <div>
          <dt>AV at fault</dt>
          <dd>{v.is_av_at_fault ? "Yes" : "No"}</dd>
        </div>
        {pct !== null && (
          <div>
            <dt>AV fault share</dt>
            <dd>{pct}%</dd>
          </div>
        )}
      </dl>
      {v.short_explanation && (
        <p className="fault-explanation">{v.short_explanation}</p>
      )}
      <p className="muted fault-footnote">
        Model {val(v.model)} · version {val(v.fault_version)}
      </p>
    </>
  );
}

function areas(list: string[]): string {
  return list.length > 0 ? list.join(", ") : "None reported";
}

// Map a free-text severity to a tone class. The dataset's wording varies, so we
// match on substrings and fall back to a neutral badge rather than guessing.
function severityTone(s: string): string {
  const t = s.toLowerCase();
  if (t.includes("fatal")) return "sev--fatal";
  if (t.includes("serious")) return "sev--serious";
  if (t.includes("moderate")) return "sev--moderate";
  if (t.includes("minor")) return "sev--minor";
  if (t.includes("none") || t.startsWith("no ")) return "sev--none";
  return "sev--unknown";
}

// Raw one-pager field groups (plan R3). Rendered in order; every field shown,
// '—' for blanks — required fields are never dropped silently.
function fieldGroups(
  d: IncidentDetail,
): { title: string; fields: [string, string][] }[] {
  return [
    {
      title: "Report",
      fields: [
        ["Report ID", val(d.report_id)],
        ["Reporting Entity", val(d.reporting_entity)],
        ["Operating Entity", val(d.operating_entity)],
        ["Incident Date", val(d.incident_date)],
        ["Incident Time", val(d.incident_time)],
        ["City", val(d.city)],
        ["State", val(d.state)],
      ],
    },
    {
      title: "Crash",
      fields: [
        ["Crash With", val(d.crash_with)],
        ["Highest Injury Severity Alleged", val(d.severity)],
        ["Property Damage", val(d.property_damage)],
        ["Roadway Type", val(d.roadway_type)],
        ["Roadway Description", val(d.roadway_description)],
        ["Law Enforcement Investigating", val(d.law_enforcement_investigating)],
      ],
    },
    {
      title: "Vehicles",
      fields: [
        ["CP Pre-Crash Movement", val(d.cp_pre_crash_movement)],
        ["SV Pre-Crash Movement", val(d.sv_pre_crash_movement)],
        ["CP Airbags Deployed", val(d.cp_airbags_deployed)],
        ["SV Airbags Deployed", val(d.sv_airbags_deployed)],
        ["CP Vehicle Towed", val(d.cp_vehicle_towed)],
        ["SV Vehicle Towed", val(d.sv_vehicle_towed)],
        ["Passengers Belted", val(d.passengers_belted)],
        ["SV Pre-Crash Speed (MPH)", val(d.precrash_speed)],
        ["CP Contact Areas", areas(d.cp_contact_areas)],
        ["SV Contact Areas", areas(d.sv_contact_areas)],
      ],
    },
  ];
}

export default async function IncidentDetailPage({
  params,
  searchParams,
}: {
  params: Promise<{ reportId: string }>;
  searchParams?: Promise<{ view?: string }>;
}) {
  const { reportId } = await params;
  const { view } = (await searchParams) ?? {};
  const initialView: TabId = isTabId(view) ? view : "verdict";
  // Fault verdict loads in parallel; it's read-only and independent of the
  // incident lookup, so a missing verdict never blocks the page.
  const [result, faultResult] = await Promise.all([
    fetchIncident(reportId),
    fetchFault(reportId),
  ]);

  if (!result.ok) {
    return (
      <main>
        <p>
          <Link href="/">← Back to incidents</Link>
        </p>
        <h1>Incident</h1>
        <p className="notice">
          {result.error === "notfound"
            ? `No incident found for report ${reportId}.`
            : "Could not load this incident. The data service may be unavailable."}
        </p>
      </main>
    );
  }

  const d = result.data;
  const severity = val(d.severity);
  const location = [val(d.city), val(d.state)]
    .filter((s) => s !== "—")
    .join(", ");

  // Persistent context: identity, the key crash facts, and the narrative stay
  // pinned above the tabs — every reasoning surface below is meaningless
  // without them, so they must never scroll out of reach.
  const header = (
    <header className="incident-head">
      <div className="incident-head__title">
        <h1>
          {val(d.reporting_entity)} · {val(d.incident_date)}
        </h1>
        {severity !== "—" && (
          <span className={`sev-badge ${severityTone(severity)}`}>
            {severity}
          </span>
        )}
      </div>
      <p className="incident-head__meta muted">
        Report {val(d.report_id)}
        {location ? ` · ${location}` : ""} · vs. {val(d.crash_with)}
      </p>
      <section className="incident-head__narrative">
        <h2>Narrative</h2>
        <div className="narrative">{val(d.narrative)}</div>
      </section>
    </header>
  );

  const verdictPanel = (
    <>
      <p className="muted tab-lede">
        An LLM reads this report&apos;s narrative and structured fields and
        renders a single fault opinion — the &ldquo;judge&rdquo; pattern. It is
        computed once per report and cached.
      </p>
      <FaultBlock fault={faultResult} />
    </>
  );

  const reportPanel = (
    <>
      <p className="muted tab-lede">
        Every field exactly as reported to NHTSA — nothing inferred. Blank
        values show as &ldquo;—&rdquo;.
      </p>
      {d.other_reports.length > 0 && (
        <section>
          <h2>Other reports of this incident</h2>
          <ul>
            {d.other_reports.map((r) => (
              <li key={r.report_id}>
                <Link href={`/incidents/${encodeURIComponent(r.report_id)}`}>
                  {r.report_id}
                </Link>
                {r.reporting_entity ? ` — ${r.reporting_entity}` : null}
              </li>
            ))}
          </ul>
        </section>
      )}
      {fieldGroups(d).map((group) => (
        <section key={group.title}>
          <h2>{group.title}</h2>
          <dl className="detail-grid">
            {group.fields.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </>
  );

  return (
    <main>
      <p>
        <Link href="/">← Back to incidents</Link>
      </p>
      {header}
      <IncidentTabs
        initialView={initialView}
        verdict={verdictPanel}
        debate={<DebatePanel reportId={reportId} />}
        report={reportPanel}
      />
    </main>
  );
}
