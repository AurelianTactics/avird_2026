import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import RagAsk from "./RagAsk";
import type { RagResult } from "../lib/api";

const realFetch = global.fetch;

function mockResult(result: RagResult) {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: async () => result,
    } as unknown as Response),
  ) as unknown as typeof fetch;
}

const SUCCESS: RagResult = {
  question: "pedestrians at night",
  answer: "A pedestrian was struck in a marked crosswalk at night [1].",
  cited_incident_ids: ["inc-1"],
  retrieved_ids: ["inc-1", "inc-2"],
  retrieved: [
    {
      incident_id: "inc-1",
      narrative: "A pedestrian entered the crosswalk...",
      distance: 0.12,
    },
    {
      incident_id: "inc-2",
      narrative: "The ADS was stopped when...",
      distance: 0.31,
    },
  ],
  supported: true,
  refused: false,
  iterations: 1,
  fallback: false,
  message: "",
};

describe("RagAsk", () => {
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("submits a question and renders the cited answer + retrieved narratives", async () => {
    mockResult(SUCCESS);
    const { container, getByLabelText } = render(<RagAsk />);
    fireEvent.change(getByLabelText(/Ask about the crash narratives/i), {
      target: { value: "pedestrians at night" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".rag-answer")?.textContent).toContain(
        "marked crosswalk",
      );
    });
    // Faithfulness verdict + cited provenance + the narratives the model read.
    expect(container.textContent).toContain("faithful");
    expect(container.textContent).toContain("inc-1");
    expect(container.textContent).toContain("2 retrieved narratives");
    expect(container.textContent).toContain("The ADS was stopped when");
  });

  it("marks an unverified answer when the judge did not confirm support", async () => {
    mockResult({ ...SUCCESS, supported: false, iterations: 2 });
    const { container } = render(<RagAsk />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "pedestrians" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.textContent).toContain("unverified");
    });
    expect(container.textContent).toContain("2 attempts");
  });

  it("renders a refusal as an honest notice, not an answer", async () => {
    mockResult({
      ...SUCCESS,
      answer: "NOT SUPPORTED BY THE DATA",
      cited_incident_ids: [],
      refused: true,
    });
    const { container } = render(<RagAsk />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "what is the meaning of life?" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".notice")).not.toBeNull();
    });
    expect(container.textContent).toContain("refused rather than guessing");
  });

  it("renders a subtle notice with relevant incidents on a fallback result", async () => {
    mockResult({
      ...SUCCESS,
      answer: "",
      cited_incident_ids: [],
      supported: false,
      fallback: true,
      message: "The narrative-RAG service is busy right now — try again later.",
    });
    const { container } = render(<RagAsk />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "pedestrians" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".notice")).not.toBeNull();
    });
    expect(container.textContent).toContain("busy right now");
    // Retrieval-only degrade still shows the most relevant incidents.
    expect(container.textContent).toContain("inc-2");
  });
});
