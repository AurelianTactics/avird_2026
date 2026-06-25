import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

// The graph is a client component that lazily imports vis-network (a DOM/canvas
// library). Stub it so this test exercises only the server-rendered prose/data.
vi.mock("./OntologyGraph", () => ({ default: () => null }));

import OntologyPage from "./page";

describe("OntologyPage", () => {
  it("renders the title and every pipeline stage", () => {
    const { container } = render(<OntologyPage />);
    expect(container.textContent).toContain(
      "An ontology over AV crash narratives",
    );
    expect(container.textContent).toContain("Seed the schema from columns");
    expect(container.textContent).toContain("Evaluate against a golden set");
  });

  it("surfaces run stats and competency questions from the generated data", () => {
    const { container } = render(<OntologyPage />);
    expect(container.textContent).toContain("hallucinations caught");
    expect(container.textContent).toContain("consolidation F1");
    // At least one competency question from schema/v001.yaml made it through.
    expect(container.querySelectorAll(".onto-cqs li").length).toBeGreaterThan(
      0,
    );
  });

  it("marks the takeaways as a draft to revise", () => {
    const { container } = render(<OntologyPage />);
    expect(container.textContent).toContain("Draft");
  });
});
