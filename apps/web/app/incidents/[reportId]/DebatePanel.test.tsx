import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import DebatePanel from "./DebatePanel";

const realFetch = global.fetch;

function jsonRes(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

function routeFetch(opts: { turn?: () => Response; judge?: () => Response }) {
  global.fetch = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/turn")) {
      return Promise.resolve(
        (
          opts.turn ??
          (() =>
            jsonRes(200, {
              message: "The AV is not at fault.",
              ai_position: "not_at_fault",
              round: 1,
            }))
        )(),
      );
    }
    if (url.endsWith("/judge")) {
      return Promise.resolve(
        (
          opts.judge ??
          (() =>
            jsonRes(200, {
              is_av_at_fault: true,
              fault_percentage: 0.75,
              reasoning: "The AV failed to yield.",
            }))
        )(),
      );
    }
    return Promise.reject(new Error(`unexpected fetch: ${url}`));
  }) as unknown as typeof fetch;
}

async function argue(text: string) {
  fireEvent.change(screen.getByLabelText("Your argument"), {
    target: { value: text },
  });
  fireEvent.click(screen.getByRole("button", { name: "Send argument" }));
}

describe("DebatePanel", () => {
  beforeEach(() => routeFetch({}));
  afterEach(() => {
    global.fetch = realFetch;
    vi.restoreAllMocks();
  });

  it("shows side-picker buttons before a side is chosen", () => {
    render(<DebatePanel reportId="RPT-9" />);
    expect(
      screen.getByRole("button", { name: "The AV is at fault" }),
    ).toBeDefined();
    expect(
      screen.getByRole("button", { name: "The AV is not at fault" }),
    ).toBeDefined();
    // No argument input until a side is picked.
    expect(screen.queryByLabelText("Your argument")).toBeNull();
  });

  it("walks pick-side -> argue -> rebuttal -> verdict", async () => {
    render(<DebatePanel reportId="RPT-9" />);
    fireEvent.click(screen.getByRole("button", { name: "The AV is at fault" }));

    expect(screen.getByText(/You are arguing:/)).toBeDefined();

    await argue("The AV ran the red light.");

    // The visitor's argument and the AI rebuttal both land in the transcript.
    await screen.findByText(/The AV ran the red light\./);
    expect(screen.getByText(/The AV is not at fault\./)).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Request verdict" }));

    await screen.findByText("The judge's verdict");
    expect(screen.getByText(/75%/)).toBeDefined();
    expect(screen.getByText(/failed to yield/)).toBeDefined();
    // Input is gone once a verdict is rendered.
    expect(screen.queryByLabelText("Your argument")).toBeNull();
  });

  it("enforces the round cap in the UI", async () => {
    const { container } = render(<DebatePanel reportId="RPT-9" />);
    fireEvent.click(screen.getByRole("button", { name: "The AV is at fault" }));

    for (let i = 0; i < 5; i++) {
      await argue(`argument ${i}`);
      // Wait until this round's user message lands before sending the next.
      await waitFor(() =>
        expect(container.querySelectorAll(".debate-msg--user").length).toBe(
          i + 1,
        ),
      );
    }

    const textarea = screen.getByLabelText(
      "Your argument",
    ) as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "Send argument",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("shows a friendly error when the budget guard trips (429)", async () => {
    routeFetch({
      turn: () =>
        jsonRes(429, {
          error: "AI debates are taking a break — try again later.",
        }),
    });
    render(<DebatePanel reportId="RPT-9" />);
    fireEvent.click(screen.getByRole("button", { name: "The AV is at fault" }));
    await argue("My argument.");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("taking a break");
  });

  it("disables Send while a turn is in flight (loading state)", async () => {
    let resolveTurn: (r: Response) => void = () => {};
    routeFetch({
      turn: () => {
        throw new Error("should not be called synchronously");
      },
    });
    global.fetch = vi.fn(
      () => new Promise<Response>((resolve) => (resolveTurn = resolve)),
    ) as unknown as typeof fetch;

    render(<DebatePanel reportId="RPT-9" />);
    fireEvent.click(screen.getByRole("button", { name: "The AV is at fault" }));
    fireEvent.change(screen.getByLabelText("Your argument"), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send argument" }));

    // While the promise is unresolved, the button shows the loading label.
    await screen.findByRole("button", { name: "Thinking…" });

    resolveTurn(
      jsonRes(200, { message: "ok", ai_position: "not_at_fault", round: 1 }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Thinking…" })).toBeNull(),
    );
  });
});
