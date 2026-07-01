import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import RagPage from "./page";
import type { RagStatus } from "../lib/api";

const realFetch = global.fetch;

function mockFetch(impl: () => Response) {
  global.fetch = vi.fn(() =>
    Promise.resolve(impl()),
  ) as unknown as typeof fetch;
}

function ok(body: RagStatus): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

describe("RagPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("renders the stable prose intro needle", async () => {
    mockFetch(() => ok({ available: true, corpus_size: 3200 }));
    const { container } = render(await RagPage());
    expect(container.textContent).toContain("retrieves the most similar");
  });

  it("renders the corpus size when the store is available", async () => {
    mockFetch(() => ok({ available: true, corpus_size: 3200 }));
    const { container } = render(await RagPage());
    expect(container.textContent).toContain("3,200");
    expect(container.textContent).toContain("narratives");
  });

  it("shows a graceful notice when the store is unavailable", async () => {
    mockFetch(() => ok({ available: false, corpus_size: 0 }));
    const { container } = render(await RagPage());
    expect(container.textContent).toContain("narrative index is unavailable");
    // The box still renders — questions return a service notice, not a crash.
    expect(container.textContent).toContain("retrieves the most similar");
  });

  it("shows a notice when the status fetch fails entirely", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(await RagPage());
    expect(container.textContent).toContain("narrative index is unavailable");
  });
});
