import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import KgAsk from "./KgAsk";
import type { KgResult } from "../lib/api";

const realFetch = global.fetch;

function mockResult(result: KgResult) {
  global.fetch = vi.fn(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: async () => result,
    } as unknown as Response),
  ) as unknown as typeof fetch;
}

const SUCCESS: KgResult = {
  question: "companies by incidents",
  cypher:
    "MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle) RETURN c.name AS company, count(v) AS n LIMIT 200",
  rows: [
    { company: "Waymo", n: 3 },
    { company: "Cruise", n: 2 },
  ],
  row_count: 2,
  iterations: 1,
  fallback: false,
  attempts: [
    {
      iteration: 1,
      cypher:
        "MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle) RETURN c.name, count(v)",
      status: "valid",
      reason: "",
    },
  ],
  message: "",
  graph_available: true,
};

describe("KgAsk", () => {
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("submits a question and renders the Cypher + result table", async () => {
    mockResult(SUCCESS);
    const { container, getByLabelText } = render(<KgAsk />);
    fireEvent.change(getByLabelText(/Ask a question/i), {
      target: { value: "companies by incidents" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".nlsql-sql")?.textContent).toContain(
        "MATCH (c:Company)",
      );
    });
    expect(container.textContent).toContain("Waymo");
    expect(container.textContent).toContain("Result (2 rows)");
  });

  it("shows the repair trace when the loop fired", async () => {
    mockResult({
      ...SUCCESS,
      iterations: 2,
      attempts: [
        {
          iteration: 1,
          cypher: "MATCH (n) DETACH DELETE n",
          status: "invalid",
          reason:
            "write clause 'DETACH' is not allowed — read-only Cypher only",
        },
        {
          iteration: 2,
          cypher: "MATCH (c:Company) RETURN c.name",
          status: "valid",
          reason: "",
        },
      ],
    });
    const { container } = render(<KgAsk />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "delete stuff" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".nlsql-trace")).not.toBeNull();
    });
    expect(container.textContent).toContain("Repair trace");
    expect(container.textContent).toContain("invalid");
  });

  it("renders a subtle notice on a fallback result", async () => {
    mockResult({
      question: "gibberish",
      cypher: null,
      rows: [],
      row_count: 0,
      iterations: 3,
      fallback: true,
      attempts: [],
      message: "Couldn't answer that from the graph — try rephrasing.",
      graph_available: true,
    });
    const { container } = render(<KgAsk />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "??" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".notice")).not.toBeNull();
    });
    expect(container.textContent).toContain("Couldn't answer that");
  });

  it("renders the graph-down state distinctly from an ordinary fallback", async () => {
    mockResult({
      question: "anything",
      cypher: null,
      rows: [],
      row_count: 0,
      iterations: 0,
      fallback: true,
      attempts: [],
      message:
        "The knowledge graph is unreachable right now — try again later.",
      graph_available: false,
    });
    const { container } = render(<KgAsk />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "anything" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.textContent).toContain("knowledge graph is unreachable");
    });
  });
});
