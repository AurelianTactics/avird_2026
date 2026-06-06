import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import IncidentsPage from "./page";
import type { IncidentList } from "./lib/api";

const realFetch = global.fetch;

function mockFetch(impl: (url: string) => Promise<Response> | Response) {
  global.fetch = vi.fn((input: RequestInfo | URL) =>
    Promise.resolve(impl(String(input))),
  ) as unknown as typeof fetch;
}

function listResponse(body: IncidentList): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as unknown as Response;
}

const SAMPLE: IncidentList = {
  items: [
    {
      report_id: "RPT-1",
      reporting_entity: "Waymo LLC",
      incident_date: "2024-03-01",
      city: "San Francisco",
      state: "CA",
      severity: "No Apparent Injury",
      crash_with: "Passenger Car",
    },
  ],
  page: 1,
  page_size: 50,
  total: 1,
};

function sp(params: Record<string, string> = {}) {
  return Promise.resolve(params);
}

describe("IncidentsPage", () => {
  beforeEach(() => {
    process.env.API_URL = "http://api.test";
  });
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("renders rows with the raw columns and the raw severity string", async () => {
    mockFetch(() => listResponse(SAMPLE));
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    expect(container.textContent).toContain("Waymo LLC");
    expect(container.textContent).toContain("San Francisco");
    // RAW severity string, not a bucket label like "No Injuries".
    expect(container.textContent).toContain("No Apparent Injury");
    expect(container.textContent).not.toContain("No Injuries");
  });

  it("links each row to its detail page", async () => {
    mockFetch(() => listResponse(SAMPLE));
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    expect(
      container.querySelector('a[href="/incidents/RPT-1"]'),
    ).not.toBeNull();
  });

  it("default view requests sort=date&dir=desc&page=1", async () => {
    const spy = vi.fn(() => listResponse(SAMPLE));
    mockFetch(spy as unknown as (url: string) => Response);
    await IncidentsPage({ searchParams: sp() });
    const url = (global.fetch as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0][0];
    expect(String(url)).toContain("/incidents?");
    expect(String(url)).toContain("sort=date");
    expect(String(url)).toContain("dir=desc");
    expect(String(url)).toContain("page=1");
  });

  it("column headers carry sort links that flip dir and set sort", async () => {
    mockFetch(() => listResponse(SAMPLE));
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    // Active column (date, currently desc) flips to asc.
    expect(
      container.querySelector('a[href="/?sort=date&dir=asc&page=1"]'),
    ).not.toBeNull();
    // Fresh column (entity) starts ascending.
    expect(
      container.querySelector('a[href="/?sort=entity&dir=asc&page=1"]'),
    ).not.toBeNull();
  });

  it("shows next/prev reflecting total and page, suppressing next on the last page", async () => {
    mockFetch(() =>
      listResponse({ ...SAMPLE, page: 1, page_size: 50, total: 1 }),
    );
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    // Only one page: no link to page 2.
    expect(container.querySelector('a[href*="page=2"]')).toBeNull();
    expect(container.textContent).toContain("Page 1 of 1");
  });

  it("shows a next link when more pages exist", async () => {
    mockFetch(() =>
      listResponse({ ...SAMPLE, page: 1, page_size: 50, total: 120 }),
    );
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    expect(
      container.querySelector('a[href="/?sort=date&dir=desc&page=2"]'),
    ).not.toBeNull();
  });

  it("renders a readable fallback when the API is unreachable", async () => {
    mockFetch(() => {
      throw new Error("network");
    });
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    expect(container.textContent).toContain("Could not load incidents");
  });

  it("renders a readable fallback on a non-2xx response", async () => {
    mockFetch(
      () =>
        ({
          ok: false,
          status: 500,
          json: async () => ({}),
        }) as unknown as Response,
    );
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    expect(container.textContent).toContain("Could not load incidents");
  });

  it('shows a "no incidents" message on an empty list', async () => {
    mockFetch(() =>
      listResponse({ items: [], page: 1, page_size: 50, total: 0 }),
    );
    const { container } = render(await IncidentsPage({ searchParams: sp() }));
    expect(container.textContent).toContain("No incidents found");
  });
});
