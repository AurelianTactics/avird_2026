import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import KgPage from "./page";
import type { KgStatus } from "../lib/api";

const realFetch = global.fetch;

const STATUS: KgStatus = {
  available: true,
  nodes: 431,
  relationships: 987,
  card: {
    labels: ["Incident", "Vehicle", "Company"],
    relationship_types: ["INVOLVES", "OPERATED_BY"],
    patterns: [
      ["Incident", "INVOLVES", "Vehicle"],
      ["Vehicle", "OPERATED_BY", "Company"],
    ],
  },
};

function mockFetch(impl: () => Response) {
  global.fetch = vi.fn(() =>
    Promise.resolve(impl()),
  ) as unknown as typeof fetch;
}

function ok(body: KgStatus): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

describe("KgPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("renders the stable prose intro needle", async () => {
    mockFetch(() => ok(STATUS));
    const { container } = render(await KgPage());
    expect(container.textContent).toContain("writes a real Cypher query");
  });

  it("always shows the subgraph-coverage banner", async () => {
    mockFetch(() => ok(STATUS));
    const { container } = render(await KgPage());
    expect(container.textContent).toContain("extracted subgraph");
    expect(container.textContent).toContain("143");
  });

  it("renders the schema card and live counts from the fetched status", async () => {
    mockFetch(() => ok(STATUS));
    const { container } = render(await KgPage());
    expect(container.textContent).toContain("Incident");
    expect(container.textContent).toContain("OPERATED_BY");
    expect(container.textContent).toContain("431");
    expect(container.textContent).toContain("987");
    expect(container.textContent).toContain("2 connection patterns");
  });

  it("shows the unreachable notice but keeps the card when the graph is down", async () => {
    mockFetch(() =>
      ok({ ...STATUS, available: false, nodes: 0, relationships: 0 }),
    );
    const { container } = render(await KgPage());
    expect(container.textContent).toContain("knowledge graph is unreachable");
    // The card comes from the committed yaml — still rendered for grounding.
    expect(container.textContent).toContain("Incident");
    // The coverage banner stays regardless.
    expect(container.textContent).toContain("extracted subgraph");
  });

  it("shows a notice when the status fetch fails entirely", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(await KgPage());
    expect(container.textContent).toContain("schema card is unavailable");
    // The box still renders — questions still work server-side.
    expect(container.textContent).toContain("writes a real Cypher query");
  });
});
