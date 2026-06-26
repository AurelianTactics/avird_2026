import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import HeatmapsPage from "./page";
import type { Heatmaps } from "../lib/api";

const realFetch = global.fetch;

const HEATMAPS: Heatmaps = {
  contact_areas: {
    sv_axis: ["Front", "Left"],
    cp_axis: ["Rear", "Right"],
    cells: [
      { sv: "Front", cp: "Rear", count: 5 },
      { sv: "Left", cp: "Right", count: 2 },
    ],
  },
  pre_crash: {
    sv_axis: ["Going Straight"],
    cp_axis: ["Stopped"],
    cells: [{ sv: "Going Straight", cp: "Stopped", count: 3 }],
  },
  applied_filter: {},
};

function mockFetch(impl: () => Response) {
  global.fetch = vi.fn(() =>
    Promise.resolve(impl()),
  ) as unknown as typeof fetch;
}

function ok(body: Heatmaps): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

describe("HeatmapsPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("always renders the stable prose intro needle", async () => {
    mockFetch(() => ok(HEATMAPS));
    const { container } = render(await HeatmapsPage());
    expect(container.textContent).toContain(
      "Two derived views over the canonical",
    );
  });

  it("renders both heatmap sections from server-fetched default data", async () => {
    mockFetch(() => ok(HEATMAPS));
    const { container } = render(await HeatmapsPage());
    expect(container.textContent).toContain("Contact areas");
    expect(container.textContent).toContain("Pre-crash movements");
    // Cells rendered from the default data.
    expect(container.querySelector(".heatmap__cell")).not.toBeNull();
  });

  it("shows a readable fallback notice when the default fetch fails", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(await HeatmapsPage());
    expect(container.textContent).toContain("Could not load heatmaps");
    // The prose intro still renders (the needle is data-state independent).
    expect(container.textContent).toContain(
      "Two derived views over the canonical",
    );
  });
});
