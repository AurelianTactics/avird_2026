import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import HeatmapViews from "./HeatmapViews";
import type { Heatmaps, HeatmapQueryResult } from "../lib/api";

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

const FILTERED: HeatmapQueryResult = {
  contact_areas: {
    sv_axis: ["Front"],
    cp_axis: ["Rear"],
    cells: [{ sv: "Front", cp: "Rear", count: 9 }],
  },
  pre_crash: { sv_axis: [], cp_axis: [], cells: [] },
  applied_filter: { entity: "Waymo" },
  fallback: false,
  message: "",
};

function mockJson(body: unknown) {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: async () => body,
    } as unknown as Response),
  ) as unknown as typeof fetch;
}

afterEach(() => {
  global.fetch = realFetch;
  vi.restoreAllMocks();
});

describe("HeatmapViews", () => {
  it("renders a labelled query input", () => {
    const { getByLabelText } = render(<HeatmapViews initial={HEATMAPS} />);
    expect(getByLabelText("Filter the views in plain English")).not.toBeNull();
  });

  it("submitting calls the proxy and re-renders with the filtered matrices", async () => {
    mockJson(FILTERED);
    const { getByLabelText, getByText, container } = render(
      <HeatmapViews initial={HEATMAPS} />,
    );
    fireEvent.change(getByLabelText("Filter the views in plain English"), {
      target: { value: "only Waymo" },
    });
    fireEvent.click(getByText("Apply"));

    await waitFor(() =>
      expect(container.textContent).toContain("entity: Waymo"),
    );
    // The filtered cell (count 9) is now shown.
    expect(
      container.querySelector('[aria-label="SV Front, CP Rear: 9"]'),
    ).not.toBeNull();
    // Proxy was called same-origin.
    const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/heatmaps/query");
  });

  it("on fallback keeps the default views and shows a subtle note", async () => {
    mockJson({
      contact_areas: { sv_axis: [], cp_axis: [], cells: [] },
      pre_crash: { sv_axis: [], cp_axis: [], cells: [] },
      applied_filter: {},
      fallback: true,
      message: "Couldn't apply that filter — showing all incidents.",
    });
    const { getByLabelText, getByText, container } = render(
      <HeatmapViews initial={HEATMAPS} />,
    );
    fireEvent.change(getByLabelText("Filter the views in plain English"), {
      target: { value: "only Atlantis" },
    });
    fireEvent.click(getByText("Apply"));

    await waitFor(() =>
      expect(container.textContent).toContain("Couldn't apply that filter"),
    );
    // Default data restored: the count-5 cell is still present.
    expect(
      container.querySelector('[aria-label="SV Front, CP Rear: 5"]'),
    ).not.toBeNull();
  });

  it("coarse/fine toggle changes grouping without a refetch", () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
    const { getByText, container } = render(
      <HeatmapViews initial={HEATMAPS} />,
    );
    // Fine grouping renders the per-direction "Left" row header.
    expect(container.textContent).toContain("Left");
    fireEvent.click(getByText("Front / rear / side"));
    // Coarse grouping folds Left/Right into "Side".
    expect(container.querySelector('[aria-label*="Side"]')).not.toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("cells are keyboard-reachable buttons with accessible labels", () => {
    const { container } = render(<HeatmapViews initial={HEATMAPS} />);
    const cell = container.querySelector(
      'button.heatmap__cell[aria-label="SV Front, CP Rear: 5"]',
    );
    expect(cell).not.toBeNull();
  });

  it("shows an empty-state message per view when matrices are empty", () => {
    const empty: Heatmaps = {
      contact_areas: { sv_axis: [], cp_axis: [], cells: [] },
      pre_crash: { sv_axis: [], cp_axis: [], cells: [] },
      applied_filter: {},
    };
    const { container } = render(<HeatmapViews initial={empty} />);
    expect(container.textContent).toContain("No contact-area pairs");
    expect(container.textContent).toContain("No pre-crash movement pairs");
  });
});
