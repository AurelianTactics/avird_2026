import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import IncidentDetailPage from "./page";
import type { IncidentDetail } from "../../lib/api";

const realFetch = global.fetch;

function mockFetch(impl: () => Response) {
  global.fetch = vi.fn(() =>
    Promise.resolve(impl()),
  ) as unknown as typeof fetch;
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
    mockFetch(
      () =>
        ({
          ok: true,
          status: 200,
          json: async () => DETAIL,
        }) as unknown as Response,
    );
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    const text = container.textContent ?? "";
    expect(text).toContain("Cruise LLC");
    expect(text).toContain("Phoenix");
    expect(text).toContain("Minor");
    expect(text).toContain("Proceeding straight");
    // Contact areas collapsed to a readable list.
    expect(text).toContain("Front");
    expect(text).toContain("Left");
  });

  it("renders the narrative block", async () => {
    mockFetch(
      () =>
        ({
          ok: true,
          status: 200,
          json: async () => DETAIL,
        }) as unknown as Response,
    );
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.querySelector(".narrative")?.textContent).toContain(
      "struck while stopped",
    );
  });

  it("shows a not-found message when the API returns 404", async () => {
    mockFetch(
      () =>
        ({
          ok: false,
          status: 404,
          json: async () => ({}),
        }) as unknown as Response,
    );
    const { container } = render(
      await IncidentDetailPage({ params: params("missing") }),
    );
    expect(container.textContent).toContain(
      "No incident found for report missing",
    );
  });

  it("shows a readable fallback when the API is unreachable", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.textContent).toContain("Could not load this incident");
  });

  it("includes a back-to-list link", async () => {
    mockFetch(
      () =>
        ({
          ok: true,
          status: 200,
          json: async () => DETAIL,
        }) as unknown as Response,
    );
    const { container } = render(
      await IncidentDetailPage({ params: params() }),
    );
    expect(container.querySelector('a[href="/"]')).not.toBeNull();
  });
});
