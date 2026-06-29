import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchHeatmaps, fetchRedactionStats } from "./api";

const realFetch = global.fetch;

function okResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

describe("derived fetchers", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("fetchHeatmaps returns ok data on 200", async () => {
    const data = {
      contact_areas: { sv_axis: [], cp_axis: [], cells: [] },
      pre_crash: { sv_axis: [], cp_axis: [], cells: [] },
      applied_filter: {},
    };
    global.fetch = vi.fn(() =>
      Promise.resolve(okResponse(data)),
    ) as unknown as typeof fetch;
    const result = await fetchHeatmaps();
    expect(result).toEqual({ ok: true, data });
  });

  it("fetchHeatmaps returns unreachable on network failure", async () => {
    global.fetch = vi.fn(() => {
      throw new Error("network");
    }) as unknown as typeof fetch;
    expect(await fetchHeatmaps()).toEqual({ ok: false, error: "unreachable" });
  });

  it("fetchRedactionStats returns ok data on 200", async () => {
    const data = { redaction: [{ entity: "Waymo", redacted: 1, total: 4, share: 0.25 }] };
    global.fetch = vi.fn(() =>
      Promise.resolve(okResponse(data)),
    ) as unknown as typeof fetch;
    expect(await fetchRedactionStats()).toEqual({ ok: true, data });
  });

  it("fetchRedactionStats returns unreachable on network failure", async () => {
    global.fetch = vi.fn(() => {
      throw new Error("network");
    }) as unknown as typeof fetch;
    expect(await fetchRedactionStats()).toEqual({
      ok: false,
      error: "unreachable",
    });
  });
});
