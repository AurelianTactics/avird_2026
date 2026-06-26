import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import RedactionStats from "./RedactionStats";
import type {
  ApiResult,
  RedactionStats as RedactionStatsData,
} from "../lib/api";

function renderWith(result: ApiResult<RedactionStatsData>) {
  return render(<RedactionStats result={result} />);
}

describe("RedactionStats", () => {
  it("renders a row per entity with redacted, total, and % redacted", () => {
    const { container } = renderWith({
      ok: true,
      data: {
        redaction: [
          { entity: "Waymo", redacted: 3, total: 12, share: 0.25 },
          { entity: "Zoox", redacted: 0, total: 5, share: 0 },
        ],
      },
    });
    const rows = Array.from(container.querySelectorAll("tbody tr")).map((tr) =>
      Array.from(tr.querySelectorAll("td")).map((td) => td.textContent?.trim()),
    );
    expect(rows).toEqual([
      ["Waymo", "3", "12", "25.0%"],
      ["Zoox", "0", "5", "0.0%"], // clean entity → 0%
    ]);
  });

  it("sorts by share descending", () => {
    const { container } = renderWith({
      ok: true,
      data: {
        redaction: [
          { entity: "Low", redacted: 1, total: 100, share: 0.01 },
          { entity: "High", redacted: 9, total: 10, share: 0.9 },
        ],
      },
    });
    const first = container.querySelector("tbody tr td")?.textContent?.trim();
    expect(first).toBe("High");
  });

  it("shows a readable fallback notice on an unreachable fetch", () => {
    const { container } = renderWith({ ok: false, error: "unreachable" });
    expect(container.textContent).toContain("Could not load redaction stats");
    expect(container.querySelector("table")).toBeNull();
  });

  it("shows an empty-state message when there are no rows", () => {
    const { container } = renderWith({ ok: true, data: { redaction: [] } });
    expect(container.textContent).toContain("No redaction data available");
    expect(container.querySelector("table")).toBeNull();
  });
});
