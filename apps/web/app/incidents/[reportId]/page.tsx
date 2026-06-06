import Link from "next/link";
import { fetchIncident, type IncidentDetail } from "../../lib/api";

export const dynamic = "force-dynamic";

function val(v: string | null | undefined): string {
  const s = (v ?? "").trim();
  return s === "" ? "—" : s;
}

function areas(list: string[]): string {
  return list.length > 0 ? list.join(", ") : "None reported";
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
}: {
  params: Promise<{ reportId: string }>;
}) {
  const { reportId } = await params;
  const result = await fetchIncident(reportId);

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
  return (
    <main>
      <p>
        <Link href="/">← Back to incidents</Link>
      </p>
      <h1>
        {val(d.reporting_entity)} · {val(d.incident_date)}
      </h1>
      <p className="muted">Report {val(d.report_id)} — raw reported fields.</p>

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

      <section>
        <h2>Narrative</h2>
        <div className="narrative">{val(d.narrative)}</div>
      </section>
    </main>
  );
}
