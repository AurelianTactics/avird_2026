import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, waitFor } from "@testing-library/react";
import NlSqlQuery from "./NlSqlQuery";
import type { NlSqlResult } from "../lib/api";

const realFetch = global.fetch;

function mockResult(result: NlSqlResult) {
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, status: 200, json: async () => result } as unknown as Response),
  ) as unknown as typeof fetch;
}

const SUCCESS: NlSqlResult = {
  question: "list companies",
  sql: "SELECT master_entity FROM treated_incident_reports LIMIT 1000",
  rows: [{ master_entity: "Waymo" }, { master_entity: "Cruise" }],
  row_count: 2,
  iterations: 1,
  fallback: false,
  attempts: [{ iteration: 1, sql: "SELECT master_entity FROM treated_incident_reports", status: "valid", reason: "" }],
  message: "",
};

describe("NlSqlQuery", () => {
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("submits a question and renders the SQL + result table", async () => {
    mockResult(SUCCESS);
    const { container, getByLabelText } = render(<NlSqlQuery />);
    fireEvent.change(getByLabelText(/Ask a question/i), {
      target: { value: "list companies" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".nlsql-sql")?.textContent).toContain(
        "SELECT master_entity",
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
        { iteration: 1, sql: "DROP TABLE treated_incident_reports", status: "invalid", reason: "only read-only SELECT statements are allowed" },
        { iteration: 2, sql: "SELECT master_entity FROM treated_incident_reports", status: "valid", reason: "" },
      ],
    });
    const { container } = render(<NlSqlQuery />);
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
      sql: null,
      rows: [],
      row_count: 0,
      iterations: 3,
      fallback: true,
      attempts: [],
      message: "Couldn't answer that from the data — try rephrasing.",
    });
    const { container } = render(<NlSqlQuery />);
    fireEvent.change(container.querySelector("input")!, {
      target: { value: "??" },
    });
    fireEvent.submit(container.querySelector("form")!);

    await waitFor(() => {
      expect(container.querySelector(".notice")).not.toBeNull();
    });
    expect(container.textContent).toContain("Couldn't answer that");
  });
});
