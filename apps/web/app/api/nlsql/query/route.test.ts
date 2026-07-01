import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const realFetch = global.fetch;

function post(body: unknown): Request {
  return new Request("http://localhost/api/nlsql/query", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const RESULT = {
  question: "list companies",
  sql: "SELECT master_entity FROM treated_incident_reports LIMIT 1000",
  rows: [{ master_entity: "Waymo" }],
  row_count: 1,
  iterations: 1,
  fallback: false,
  attempts: [],
  message: "",
};

describe("POST /api/nlsql/query", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    delete process.env.API_SHARED_SECRET;
    vi.restoreAllMocks();
  });

  it("forwards question to the API and returns its JSON", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => RESULT,
      } as unknown as Response),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await POST(post({ question: "list companies" }));
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(RESULT);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/nlsql/query");
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({
      question: "list companies",
    });
  });

  it("attaches the internal secret header when API_SHARED_SECRET is set", async () => {
    process.env.API_SHARED_SECRET = "s3cret";
    const fetchMock = vi.fn(() =>
      Promise.resolve({
        ok: true,
        status: 200,
        json: async () => RESULT,
      } as unknown as Response),
    );
    global.fetch = fetchMock as unknown as typeof fetch;

    await POST(post({ question: "x" }));
    const [, init] = fetchMock.mock.calls[0];
    const headers = (init as RequestInit).headers as Record<string, string>;
    expect(headers["x-internal-secret"]).toBe("s3cret");
  });

  it("returns a fallback payload (200, not 500) on upstream failure", async () => {
    global.fetch = vi.fn(() => {
      throw new Error("network");
    }) as unknown as typeof fetch;

    const res = await POST(post({ question: "list companies" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.fallback).toBe(true);
    expect(body.sql).toBeNull();
  });

  it("returns fallback when the API responds non-ok", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({ ok: false, status: 503 } as unknown as Response),
    ) as unknown as typeof fetch;

    const res = await POST(post({ question: "x" }));
    expect(res.status).toBe(200);
    expect((await res.json()).fallback).toBe(true);
  });

  it("rejects over-length text with 422 before forwarding", async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await POST(post({ question: "x".repeat(501) }));
    expect(res.status).toBe(422);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
