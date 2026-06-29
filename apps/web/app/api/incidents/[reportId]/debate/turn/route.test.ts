import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { POST } from "./route";

const realFetch = global.fetch;

function req(body: unknown) {
  return new Request("http://web.test/api/incidents/RPT-9/debate/turn", {
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
  user_position: "av_at_fault",
  transcript: [],
  user_argument: "The AV ran the light.",
};

describe("debate turn proxy handler", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.internal:8000";
  });
  afterEach(() => {
    global.fetch = realFetch;
    delete process.env.API_SHARED_SECRET;
    vi.restoreAllMocks();
  });

  it("forwards a valid request to the internal api via API_URL", async () => {
    const fetchFn = mockUpstream(200, {
      message: "rebuttal",
      ai_position: "not_at_fault",
      round: 1,
    });
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(200);
    expect(await res.json()).toMatchObject({ ai_position: "not_at_fault" });
    const calledUrl = String(fetchFn.mock.calls[0][0]);
    expect(calledUrl).toBe(
      "http://api.internal:8000/incidents/RPT-9/debate/turn",
    );
  });

  it("attaches the internal secret header when API_SHARED_SECRET is set", async () => {
    process.env.API_SHARED_SECRET = "s3cret";
    const fetchFn = mockUpstream(200, {
      message: "rebuttal",
      ai_position: "not_at_fault",
      round: 1,
    });
    await POST(req(VALID), params());
    const opts = fetchFn.mock.calls[0][1] as RequestInit;
    const headers = opts.headers as Record<string, string>;
    expect(headers["x-internal-secret"]).toBe("s3cret");
  });

  it("sends no secret header when API_SHARED_SECRET is unset", async () => {
    const fetchFn = mockUpstream(200, {
      message: "rebuttal",
      ai_position: "not_at_fault",
      round: 1,
    });
    await POST(req(VALID), params());
    const opts = fetchFn.mock.calls[0][1] as RequestInit;
    const headers = opts.headers as Record<string, string>;
    expect(headers["x-internal-secret"]).toBeUndefined();
  });

  it("rejects an oversize argument before calling the api", async () => {
    const fetchFn = mockUpstream(200, {});
    const res = await POST(
      req({ ...VALID, user_argument: "x".repeat(5000) }),
      params(),
    );
    expect(res.status).toBe(400);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("rejects a too-long transcript before calling the api", async () => {
    const fetchFn = mockUpstream(200, {});
    const transcript = Array.from({ length: 5 }, () => ({
      role: "user",
      content: "x".repeat(5000),
    }));
    const res = await POST(req({ ...VALID, transcript }), params());
    expect(res.status).toBe(400);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("rejects an invalid position before calling the api", async () => {
    const fetchFn = mockUpstream(200, {});
    const res = await POST(
      req({ ...VALID, user_position: "sideways" }),
      params(),
    );
    expect(res.status).toBe(400);
    expect(fetchFn).not.toHaveBeenCalled();
  });

  it("maps an upstream 429 to a friendly budget message", async () => {
    mockUpstream(429, { detail: "over budget" });
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(429);
    expect((await res.json()).error).toContain("break");
  });

  it("maps an upstream 5xx to 502", async () => {
    mockUpstream(500, { detail: "boom" });
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(502);
  });

  it("maps an upstream 4xx to 400", async () => {
    mockUpstream(422, { detail: "bad" });
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(400);
  });

  it("returns 502 when the api is unreachable", async () => {
    global.fetch = vi.fn(() => {
      throw new Error("network");
    }) as unknown as typeof fetch;
    const res = await POST(req(VALID), params());
    expect(res.status).toBe(502);
  });

  it("returns 400 on invalid JSON", async () => {
    const bad = new Request("http://web.test/x", {
      method: "POST",
      body: "{not json",
    });
    const res = await POST(bad, params());
    expect(res.status).toBe(400);
  });
});
