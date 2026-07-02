import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import Nav from "./Nav";

describe("Nav", () => {
  it("renders Incidents, AV Company Stats, Heatmaps, and About links with correct hrefs", () => {
    const { container } = render(<Nav />);
    expect(container.querySelector('a[href="/"]')?.textContent).toBe(
      "Incidents",
    );
    expect(container.querySelector('a[href="/groupings"]')?.textContent).toBe(
      "AV Company Stats",
    );
    expect(container.querySelector('a[href="/heatmaps"]')?.textContent).toBe(
      "Heatmaps",
    );
    expect(container.querySelector('a[href="/nlsql"]')?.textContent).toBe(
      "Ask the data",
    );
    expect(container.querySelector('a[href="/rag"]')?.textContent).toBe(
      "Ask the narratives",
    );
    expect(container.querySelector('a[href="/kg"]')?.textContent).toBe(
      "Ask the graph",
    );
    expect(container.querySelector('a[href="/about"]')?.textContent).toBe(
      "About",
    );
  });
});
