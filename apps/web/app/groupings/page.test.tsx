import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import GroupingsPage from "./page";
import type { EntitySeverityGroupings, RedactionStats } from "../lib/api";

const realFetch = global.fetch;

const REDACTION: RedactionStats = {
  redaction: [
    { entity: "Waymo", redacted: 2, total: 8, share: 0.25 },
    { entity: "Cruise", redacted: 0, total: 4, share: 0 },
  ],
};

// Endpoint-aware mock: the page fetches both the groupings matrix and the
// redaction breakdown. Route each fetch by URL so they get the right shape.
function mockFetch(opts: {
  groupings?: () => Response;
  redaction?: () => Response;
}) {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/derived/redaction")) {
      return Promise.resolve(opts.redaction ? opts.redaction() : ok(REDACTION));
    }
    if (opts.groupings) return Promise.resolve(opts.groupings());
    throw new Error(`unexpected fetch: ${url}`);
  }) as unknown as typeof fetch;
}

function okJson(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

const BUCKETS = [
  "Fatality",
  "Serious",
  "Moderate",
  "Minor",
  "No Injuries",
  "Property",
  "Unknown",
];

const DATA: EntitySeverityGroupings = {
  buckets: BUCKETS,
  rows: [
    {
      entity: "Waymo",
      counts: {
        Fatality: 1,
        Serious: 0,
        Moderate: 2,
        Minor: 3,
        "No Injuries": 10,
        Property: 4,
        Unknown: 0,
      },
      total: 20,
    },
  ],
};

function ok(body: EntitySeverityGroupings): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

describe("GroupingsPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("renders the seven buckets in order as headers", async () => {
    mockFetch({ groupings: () => ok(DATA) });
    const { container } = render(await GroupingsPage());
    const headers = Array.from(
      container.querySelectorAll("thead")[0].querySelectorAll("th"),
    ).map((th) => th.textContent?.trim());
    expect(headers).toEqual(["Entity", ...BUCKETS, "Total"]);
  });

  it("renders a row per entity with bucket cells and a total", async () => {
    mockFetch({ groupings: () => ok(DATA) });
    const { container } = render(await GroupingsPage());
    const cells = Array.from(
      container.querySelectorAll("tbody")[0].querySelectorAll("td"),
    ).map((td) => td.textContent?.trim());
    // Entity, seven buckets, total.
    expect(cells).toEqual(["Waymo", "1", "0", "2", "3", "10", "4", "0", "20"]);
  });

  it("renders count cells as plain text, not links (no drill-through)", async () => {
    mockFetch({ groupings: () => ok(DATA) });
    const { container } = render(await GroupingsPage());
    expect(container.querySelector("tbody a")).toBeNull();
  });

  it("shows a readable fallback when the API is unreachable", async () => {
    mockFetch({
      groupings: () => {
        throw new Error("network");
      },
    });
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("Could not load groupings");
  });

  it('shows a "no data" message on an empty matrix', async () => {
    mockFetch({ groupings: () => ok({ buckets: BUCKETS, rows: [] }) });
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("No grouping data available");
  });

  // --- Redaction table (U8) -------------------------------------------------

  it("renders the redaction table below the groupings table", async () => {
    mockFetch({ groupings: () => ok(DATA) });
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("Narrative redaction");
    // Two tables: the groupings matrix and the redaction breakdown.
    const tables = container.querySelectorAll("table.data-table");
    expect(tables.length).toBe(2);
    const redactionRows = Array.from(
      tables[1].querySelectorAll("tbody tr"),
    ).map((tr) =>
      Array.from(tr.querySelectorAll("td")).map((td) => td.textContent?.trim()),
    );
    expect(redactionRows[0]).toEqual(["Waymo", "2", "8", "25.0%"]);
    // A clean entity shows 0%.
    expect(redactionRows[1]).toEqual(["Cruise", "0", "4", "0.0%"]);
  });

  it("shows a redaction fallback notice while the groupings table still renders", async () => {
    mockFetch({
      groupings: () => ok(DATA),
      redaction: () => {
        throw new Error("network");
      },
    });
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("Could not load redaction stats");
    // The independent groupings fetch still rendered its table.
    expect(container.textContent).toContain("Waymo");
    expect(container.querySelector("table.data-table")).not.toBeNull();
  });

  it("shows an empty-state message when redaction data is empty", async () => {
    mockFetch({
      groupings: () => ok(DATA),
      redaction: () => okJson({ redaction: [] }),
    });
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("No redaction data available");
  });
});
