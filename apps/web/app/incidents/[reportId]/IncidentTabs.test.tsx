import { afterEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import IncidentTabs from "./IncidentTabs";

function renderTabs(initialView: "verdict" | "debate" | "report" = "verdict") {
  return render(
    <IncidentTabs
      initialView={initialView}
      verdict={<p>verdict-body</p>}
      debate={<p>debate-body</p>}
      report={<p>report-body</p>}
    />,
  );
}

function tab(name: string) {
  return screen.getByRole("tab", { name });
}

function panelOf(text: string): HTMLElement {
  return screen.getByText(text).closest("[role=tabpanel]") as HTMLElement;
}

// jsdom shares one history/location across tests; reset the query each time so
// URL assertions don't bleed between cases.
afterEach(() => {
  window.history.replaceState(null, "", "/incidents/RPT-9");
});

describe("IncidentTabs", () => {
  it("defaults to the verdict tab as the visible panel", () => {
    renderTabs();
    expect(tab("AI Verdict").getAttribute("aria-selected")).toBe("true");
    // Inactive panels stay mounted (so state survives) but are hidden.
    expect(panelOf("verdict-body").hidden).toBe(false);
    expect(panelOf("debate-body").hidden).toBe(true);
    expect(panelOf("report-body").hidden).toBe(true);
  });

  it("honors initialView for deep links", () => {
    renderTabs("debate");
    expect(tab("Argue it yourself").getAttribute("aria-selected")).toBe("true");
    expect(panelOf("debate-body").hidden).toBe(false);
  });

  it("switches the active panel and writes ?view= on click", () => {
    renderTabs();
    fireEvent.click(tab("Full report"));
    expect(tab("Full report").getAttribute("aria-selected")).toBe("true");
    expect(panelOf("report-body").hidden).toBe(false);
    expect(panelOf("verdict-body").hidden).toBe(true);
    expect(new URLSearchParams(window.location.search).get("view")).toBe(
      "report",
    );
  });

  it("moves between tabs with arrow keys", () => {
    renderTabs();
    fireEvent.keyDown(tab("AI Verdict"), { key: "ArrowRight" });
    expect(tab("Argue it yourself").getAttribute("aria-selected")).toBe("true");
  });
});
