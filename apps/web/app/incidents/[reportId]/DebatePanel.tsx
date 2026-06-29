"use client";

import { useState } from "react";

// Mirrors the caps in app/lib/debate.ts (which is server-only and must not be
// imported into client code — it reads process.env.API_URL).
const MAX_ROUNDS = 5;
const MAX_ARGUMENT_CHARS = 2000;

type Role = "user" | "ai";
type Message = { role: Role; content: string };
type Position = "av_at_fault" | "not_at_fault";
type Verdict = {
  is_av_at_fault: boolean;
  fault_percentage: number;
  reasoning: string;
};

const POSITION_LABEL: Record<Position, string> = {
  av_at_fault: "The AV is at fault",
  not_at_fault: "The AV is not at fault",
};

async function postJson(
  path: string,
  body: unknown,
): Promise<Record<string, unknown>> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
  if (!res.ok) {
    throw new Error(
      (data.error as string) ?? "Something went wrong. Try again.",
    );
  }
  return data;
}

export default function DebatePanel({ reportId }: { reportId: string }) {
  const [position, setPosition] = useState<Position | null>(null);
  const [transcript, setTranscript] = useState<Message[]>([]);
  const [argument, setArgument] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<Verdict | null>(null);

  const userRounds = transcript.filter((m) => m.role === "user").length;
  const roundsLeft = MAX_ROUNDS - userRounds;
  const roundsUsedUp = roundsLeft <= 0;

  async function sendArgument() {
    if (!position || argument.trim() === "" || loading || roundsUsedUp) return;
    const arg = argument.trim();
    setLoading(true);
    setError(null);
    try {
      const data = await postJson(
        `/api/incidents/${encodeURIComponent(reportId)}/debate/turn`,
        { user_position: position, transcript, user_argument: arg },
      );
      setTranscript([
        ...transcript,
        { role: "user", content: arg },
        { role: "ai", content: String(data.message ?? "") },
      ]);
      setArgument("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  async function requestVerdict() {
    if (loading || transcript.length === 0) return;
    setLoading(true);
    setError(null);
    try {
      const data = await postJson(
        `/api/incidents/${encodeURIComponent(reportId)}/debate/judge`,
        { transcript },
      );
      setVerdict({
        is_av_at_fault: Boolean(data.is_av_at_fault),
        fault_percentage: Number(data.fault_percentage ?? 0),
        reasoning: String(data.reasoning ?? ""),
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="debate-panel">
      <h2>Argue the fault yourself</h2>
      <p className="muted">
        Pick a side and make your case. An AI advocate argues the opposite; then
        an AI judge reads the whole debate and renders a verdict. This is an AI
        opinion for entertainment and learning — not a legal or factual
        determination.
      </p>

      {position === null ? (
        <div className="debate-pick">
          <p>Which side will you argue?</p>
          <button type="button" onClick={() => setPosition("av_at_fault")}>
            {POSITION_LABEL.av_at_fault}
          </button>
          <button type="button" onClick={() => setPosition("not_at_fault")}>
            {POSITION_LABEL.not_at_fault}
          </button>
        </div>
      ) : (
        <>
          <p className="debate-side">
            You are arguing: <strong>{POSITION_LABEL[position]}</strong>
          </p>

          {transcript.length > 0 && (
            <ol className="debate-transcript">
              {transcript.map((m, i) => (
                <li key={i} className={`debate-msg debate-msg--${m.role}`}>
                  <span className="debate-speaker">
                    {m.role === "user" ? "You" : "AI advocate"}:
                  </span>{" "}
                  {m.content}
                </li>
              ))}
            </ol>
          )}

          {verdict === null && (
            <>
              <p className="debate-rounds">
                Round {Math.min(userRounds + 1, MAX_ROUNDS)} of {MAX_ROUNDS}
              </p>
              <textarea
                aria-label="Your argument"
                className="debate-input"
                maxLength={MAX_ARGUMENT_CHARS}
                value={argument}
                onChange={(e) => setArgument(e.target.value)}
                disabled={loading || roundsUsedUp}
                placeholder={
                  roundsUsedUp
                    ? "You've used all your rounds — request a verdict."
                    : "Make your argument…"
                }
              />
              <div className="debate-controls">
                <button
                  type="button"
                  onClick={sendArgument}
                  disabled={loading || roundsUsedUp || argument.trim() === ""}
                >
                  {loading ? "Thinking…" : "Send argument"}
                </button>
                <button
                  type="button"
                  onClick={requestVerdict}
                  disabled={loading || transcript.length === 0}
                >
                  Request verdict
                </button>
              </div>
            </>
          )}

          {error && (
            <p className="notice debate-error" role="alert">
              {error}
            </p>
          )}

          {verdict && (
            <div className="debate-verdict">
              <h3>The judge&apos;s verdict</h3>
              <p>
                AV at fault:{" "}
                <strong>{verdict.is_av_at_fault ? "Yes" : "No"}</strong> · Fault
                share:{" "}
                <strong>{Math.round(verdict.fault_percentage * 100)}%</strong>
              </p>
              <p className="debate-reasoning">{verdict.reasoning}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
