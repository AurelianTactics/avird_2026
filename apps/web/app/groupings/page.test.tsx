import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import GroupingsPage from "./page";
import type { EntitySeverityGroupings } from "../lib/api";

const realFetch = global.fetch;

function mockFetch(impl: () => Response) {
  global.fetch = vi.fn(() =>
    Promise.resolve(impl()),
  ) as unknown as typeof fetch;
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
    mockFetch(() => ok(DATA));
    const { container } = render(await GroupingsPage());
    const headers = Array.from(container.querySelectorAll("thead th")).map(
      (th) => th.textContent?.trim(),
    );
    expect(headers).toEqual(["Entity", ...BUCKETS, "Total"]);
  });

  it("renders a row per entity with bucket cells and a total", async () => {
    mockFetch(() => ok(DATA));
    const { container } = render(await GroupingsPage());
    const cells = Array.from(container.querySelectorAll("tbody td")).map((td) =>
      td.textContent?.trim(),
    );
    // Entity, seven buckets, total.
    expect(cells).toEqual(["Waymo", "1", "0", "2", "3", "10", "4", "0", "20"]);
  });

  it("renders count cells as plain text, not links (no drill-through)", async () => {
    mockFetch(() => ok(DATA));
    const { container } = render(await GroupingsPage());
    expect(container.querySelector("tbody a")).toBeNull();
  });

  it("shows a readable fallback when the API is unreachable", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("Could not load groupings");
  });

  it('shows a "no data" message on an empty matrix', async () => {
    mockFetch(() => ok({ buckets: BUCKETS, rows: [] }));
    const { container } = render(await GroupingsPage());
    expect(container.textContent).toContain("No grouping data available");
  });
});
