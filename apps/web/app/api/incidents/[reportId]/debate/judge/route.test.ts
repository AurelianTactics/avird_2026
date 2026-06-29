import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const realFetch = global.fetch;

function req(body: unknown) {
  return new Request("http://web.test/api/incidents/RPT-9/debate/judge", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

function params(reportId = "RPT-9") {
  return { params: Promise.resolve({ reportId }) };
}

function mockUpstream(status: number, body: unknown) {
  const fn = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

const VALID = {
  transcript: [
    { role: "user", content: "AV is fine" },
    { role: "ai", content: "AV erred" },
  ],
};

describe("debate judge proxy handler", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.internal:8000";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("forwards a valid request and returns the verdict", async () => {
    const fetchFn = mockUpstream(200, {
      is_av_at_fault: true,
      fault_percentage: 0.7,
      reasoning: "AV at fault.",
    });
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ fault_percentage: 0.7 });
    expect(String(fetchFn.mock.calls[0][0])).toBe(
      "http://api.internal:8000/incidents/RPT-9/debate/judge",
    );
  });

  it("rejects a too-large transcript before calling the api", async () => {
    const fetchFn = mockUpstream(200, {});
    const transcript = Array.from({ length: 5 }, () => ({
      role: "user",
      content: "x".repeat(5000),
    }));
    const res = await POST(req({ transcript }), params());
    expect(res.status).toBe(400);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("maps an upstream 429 to a friendly budget message", async () => {
    mockUpstream(429, { detail: "over budget" });
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(429);
    expect((await res.json()).error).toContain("break");
  });

  it("returns 502 when the api is unreachable", async () => {
    global.fetch = vi.fn(() => {
      throw new Error("network");
    }) as unknown as typeof fetch;
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(502);
  });
});
