import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import NlSqlPage from "./page";
import type { NlSqlSchema } from "../lib/api";

const realFetch = global.fetch;

const SCHEMA: NlSqlSchema = {
  available: true,
  table: "treated_incident_reports",
  columns: [
    { name: "master_entity", type: "text", raw: false, identifier: "master_entity" },
    {
      name: "Highest Injury Severity Alleged",
      type: "text",
      raw: true,
      identifier: '"Highest Injury Severity Alleged"',
    },
  ],
  value_samples: { master_entity: ["Cruise", "Waymo"] },
};

function mockFetch(impl: () => Response) {
  global.fetch = vi.fn(() => Promise.resolve(impl())) as unknown as typeof fetch;
}

function ok(body: NlSqlSchema): Response {
  return { ok: true, status: 200, json: async () => body } as unknown as Response;
}

describe("NlSqlPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("renders the stable prose intro needle", async () => {
    mockFetch(() => ok(SCHEMA));
    const { container } = render(await NlSqlPage());
    expect(container.textContent).toContain("writes a real SQL query");
  });

  it("renders the column data-dictionary from the fetched schema", async () => {
    mockFetch(() => ok(SCHEMA));
    const { container } = render(await NlSqlPage());
    expect(container.textContent).toContain("treated_incident_reports");
    expect(container.textContent).toContain("master_entity");
    // Value samples surface so the user knows what to filter on.
    expect(container.textContent).toContain("Waymo");
  });

  it("shows a graceful notice when the schema is unavailable", async () => {
    mockFetch(() => ok({ ...SCHEMA, available: false, columns: [], value_samples: {} }));
    const { container } = render(await NlSqlPage());
    expect(container.textContent).toContain("column dictionary is unavailable");
    // The box still renders — questions still work server-side.
    expect(container.textContent).toContain("writes a real SQL query");
  });

  it("shows a notice when the schema fetch fails entirely", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(await NlSqlPage());
    expect(container.textContent).toContain("column dictionary is unavailable");
  });
});
