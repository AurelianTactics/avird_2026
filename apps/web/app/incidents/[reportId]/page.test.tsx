import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import IncidentDetailPage from "./page";
import type { FaultVerdict, IncidentDetail } from "../../lib/api";

const realFetch = global.fetch;

type RouteResponse = { ok: boolean; status: number; body: unknown };

// The page fetches the incident AND its fault verdict in parallel. Route the
// mock by URL so each call gets its own response (a single shared impl would
// feed the incident object into the fault block and vice versa).
function mockApi(opts: {
  incident?: RouteResponse;
  fault?: RouteResponse;
  throwOn?: "incident" | "fault" | "all";
}) {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const isFault = url.endsWith("/fault");
    if (opts.throwOn === "all" || (isFault && opts.throwOn === "fault")) {
      throw new Error("network");
    }
    if (!isFault && opts.throwOn === "incident") throw new Error("network");
    const r = isFault
      ? (opts.fault ?? { ok: false, status: 404, body: {} })
      : (opts.incident ?? { ok: true, status: 200, body: DETAIL });
    return Promise.resolve({
      ok: r.ok,
      status: r.status,
      json: async () => r.body,
    } as unknown as Response);
  }) as unknown as typeof fetch;
}

const DETAIL: IncidentDetail = {
  report_id: "RPT-9",
  reporting_entity: "Cruise LLC",
  operating_entity: "Cruise LLC",
  incident_date: "2024-05-10",
  incident_time: "14:30",
  city: "Phoenix",
  state: "AZ",
  roadway_type: "Intersection",
  roadway_description: "Four-way signalized",
  crash_with: "Passenger Car",
  severity: "Minor",
  property_damage: "Yes",
  cp_pre_crash_movement: "Stopped",
  sv_pre_crash_movement: "Proceeding straight",
  cp_airbags_deployed: "No",
  sv_airbags_deployed: "No",
  cp_vehicle_towed: "No",
  sv_vehicle_towed: "No",
  passengers_belted: "Yes",
  precrash_speed: "12",
  law_enforcement_investigating: "No",
  cp_contact_areas: ["Front"],
  sv_contact_areas: ["Left"],
  narrative: "The SV was struck while stopped at the light.",
  other_reports: [{ report_id: "RPT-10", reporting_entity: "Waymo LLC" }],
};

const VERDICT: FaultVerdict = {
  report_id: "RPT-9",
  fault_version: "mvp_0.01",
  is_av_at_fault: true,
  av_fault_percentage: 0.75,
  short_explanation: "The AV ran a red light and struck a stopped car.",
  model: "claude-haiku-4-5",
  created_at: "2026-06-25T00:00:00+00:00",
};

function params(reportId = "RPT-9") {
  return Promise.resolve({ reportId });
}

describe("IncidentDetailPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("renders the raw one-pager fields", async () => {
    mockApi({});
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Cruise LLC");
    expect(text).toContain("Phoenix");
    expect(text).toContain("Minor");
    expect(text).toContain("Proceeding straight");
    expect(text).toContain("Front");
    expect(text).toContain("Left");
  });

  it("renders the narrative block", async () => {
    mockApi({});
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.querySelector(".narrative")?.textContent).toContain(
      "struck while stopped",
    );
  });

  it("renders the narrative before the field groups", async () => {
    mockApi({});
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    const headings = Array.from(container.querySelectorAll("h2")).map(
      (h) => h.textContent,
    );
    expect(headings[0]).toBe("Narrative");
  });

  it("links other reports of the same incident", async () => {
    mockApi({});
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(
      container.querySelector('a[href="/incidents/RPT-10"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("Other reports of this incident");
  });

  it("omits the other-reports section when there are none", async () => {
    mockApi({
      incident: { ok: true, status: 200, body: { ...DETAIL, other_reports: [] } },
    });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.textContent).not.toContain(
      "Other reports of this incident",
    );
  });

  it("shows a not-found message when the API returns 404", async () => {
    mockApi({ incident: { ok: false, status: 404, body: {} } });
    const { container } = render(
      await IncidentDetailPage({ params: params("missing") }),
    );
    expect(container.textContent).toContain(
      "No incident found for report missing",
    );
  });

  it("shows a readable fallback when the API is unreachable", async () => {
    mockApi({ throwOn: "all" });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.textContent).toContain("Could not load this incident");
  });

  it("includes a back-to-list link", async () => {
    mockApi({});
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.querySelector('a[href="/"]')).not.toBeNull();
  });

  // --- Fault verdict block (R5 / R5a) --------------------------------------

  it("renders the fault verdict with percentage, explanation, and footnote", async () => {
    mockApi({ fault: { ok: true, status: 200, body: VERDICT } });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    const text = container.textContent ?? "";
    expect(text).toContain("AI fault verdict");
    expect(text).toContain("Yes"); // AV at fault
    expect(text).toContain("75%");
    expect(text).toContain("ran a red light");
    expect(text).toContain("claude-haiku-4-5");
    expect(text).toContain("mvp_0.01");
  });

  it("always shows the AI disclaimer near the verdict", async () => {
    mockApi({ fault: { ok: true, status: 200, body: VERDICT } });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.querySelector(".fault-disclaimer")?.textContent).toContain(
      "not a legal or factual determination",
    );
  });

  it("shows a graceful empty state when no verdict exists (404)", async () => {
    mockApi({ fault: { ok: false, status: 404, body: {} } });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    const text = container.textContent ?? "";
    expect(text).toContain("No AI fault verdict has been computed");
    // The disclaimer still renders in the empty state.
    expect(container.querySelector(".fault-disclaimer")).not.toBeNull();
  });

  it("shows the sentinel message when the AI could not produce a verdict", async () => {
    mockApi({
      fault: {
        ok: true,
        status: 200,
        body: { ...VERDICT, is_av_at_fault: null, av_fault_percentage: null },
      },
    });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.textContent).toContain(
      "could not produce a usable verdict",
    );
  });

  it("keeps rendering the incident when the fault service is unreachable", async () => {
    mockApi({ throwOn: "fault" });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    // Incident still renders; fault block degrades to its unavailable notice.
    expect(container.textContent).toContain("Phoenix");
    expect(container.textContent).toContain(
      "fault verdict service is currently unavailable",
    );
  });
});
