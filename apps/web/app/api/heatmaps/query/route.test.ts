import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const realFetch = global.fetch;

function post(body: unknown): Request {
  return new Request("http://localhost/api/heatmaps/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const QUERY_RESULT = {
  contact_areas: { sv_axis: ["Front"], cp_axis: ["Rear"], cells: [] },
  pre_crash: { sv_axis: [], cp_axis: [], cells: [] },
  applied_filter: { entity: "Waymo" },
  fallback: false,
  message: "",
};

describe("POST /api/heatmaps/query", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    delete process.env.API_SHARED_SECRET;
    vi.restoreAllMocks();
  });

  it("attaches the internal secret header when API_SHARED_SECRET is set", async () => {
    process.env.API_SHARED_SECRET = "s3cret";
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => QUERY_RESULT,
      } as unknown as Response),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    await POST(post({ text: "only Waymo" }));
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["x-internal-secret"]).toBe("s3cret");
  });

  it("sends no secret header when API_SHARED_SECRET is unset", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => QUERY_RESULT,
      } as unknown as Response),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    await POST(post({ text: "only Waymo" }));
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["x-internal-secret"]).toBeUndefined();
  });

  it("forwards text to the API and returns its JSON", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => QUERY_RESULT,
      } as unknown as Response),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await POST(post({ text: "only Waymo" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(QUERY_RESULT);

    // Forwarded to the server-only API_URL, with the text in the body.
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/derived/query");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      text: "only Waymo",
    });
  });

  it("reads API_URL server-side (never a NEXT_PUBLIC_ value)", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => QUERY_RESULT,
      } as unknown as Response),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    await POST(post({ text: "x" }));
    const [url] = fetchMock.mock.calls[0];
    // The handler used process.env.API_URL, not a public-prefixed var.
    expect(url).toContain("http://api.test");
    expect(process.env.NEXT_PUBLIC_API_URL).toBeUndefined();
  });

  it("returns a fallback payload (200, not 500) on upstream failure", async () => {
    global.fetch = vi.fn(() => {
      throw new Error("network");
    }) as unknown as typeof fetch;

    const res = await POST(post({ text: "only Waymo" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.fallback).toBe(true);
    expect(body.applied_filter).toEqual({});
  });

  it("returns fallback when the API responds non-ok", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: false, status: 503 } as unknown as Response),
    ) as unknown as typeof fetch;

    const res = await POST(post({ text: "only Waymo" }));
    expect(res.status).toBe(200);
    expect((await res.json()).fallback).toBe(true);
  });

  it("rejects over-length text with 422 before forwarding", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await POST(post({ text: "x".repeat(501) }));
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
