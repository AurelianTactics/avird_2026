import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import AboutPage from "./page";

describe("AboutPage", () => {
  it("renders the expected heading", () => {
    const { container } = render(<AboutPage />);
    expect(container.querySelector("h1")?.textContent).toBe("About");
  });

  it("links to the GitHub repo", () => {
    const { container } = render(<AboutPage />);
    const repoLink = container.querySelector(
      'a[href*="github.com/AurelianTactics/avird_2026"]',
    );
    expect(repoLink).not.toBeNull();
  });
});
