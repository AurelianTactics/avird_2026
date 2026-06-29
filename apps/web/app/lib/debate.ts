// Shared types, caps, validation, and the proxy helper for the debate route
// handlers (R8). The browser cannot reach the internal `api`, so `web` exposes
// thin POST handlers that enforce the same caps as the api and forward to it via
// the server-only `API_URL`. Caps are duplicated here on purpose — the proxy is
// the public edge and must reject oversize input before spending a paid call.

// Read at request time, not module load (Railway reference var). Server-only —
// no NEXT_PUBLIC_ prefix, never bundled into client code.
function apiUrl(): string {
  return process.env.API_URL ?? "http://127.0.0.1:8000";
}

// Shared secret for the internal web→api hop. Server-only (no NEXT_PUBLIC_).
// When unset (local dev) we send no header and the api skips the check; in
// production both services carry the same value. See apps/api/app/main.py.
export function internalSecretHeaders(): Record<string, string> {
  const secret = process.env.API_SHARED_SECRET;
  return secret ? { "x-internal-secret": secret } : {};
}

export const MAX_ROUNDS = 5;
export const MAX_ARGUMENT_CHARS = 2000;
export const MAX_TRANSCRIPT_CHARS = 20000;
export const MAX_TRANSCRIPT_MESSAGES = 2 * MAX_ROUNDS + 2;

export type DebateRole = "user" | "ai";
export type DebateMessage = { role: DebateRole; content: string };
export type UserPosition = "av_at_fault" | "not_at_fault";

export type TurnResponse = {
  message: string;
  ai_position: UserPosition;
  round: number;
};

export type JudgeResponse = {
  is_av_at_fault: boolean;
  fault_percentage: number; // 0..1
  reasoning: string;
};

function isMessageArray(value: unknown): value is DebateMessage[] {
  return (
    Array.isArray(value) &&
    value.every(
      (m) =>
        m !== null &&
        typeof m === "object" &&
        (m as DebateMessage).role !== undefined &&
        ((m as DebateMessage).role === "user" ||
          (m as DebateMessage).role === "ai") &&
        typeof (m as DebateMessage).content === "string",
    )
  );
}

function transcriptCapError(transcript: DebateMessage[]): string | null {
  if (transcript.length > MAX_TRANSCRIPT_MESSAGES)
    return "Transcript too long.";
  const chars = transcript.reduce((n, m) => n + m.content.length, 0);
  if (chars > MAX_TRANSCRIPT_CHARS) return "Transcript too large.";
  return null;
}

// Returns an error string when the body is invalid or over-cap, else null.
export function turnCapError(body: unknown): string | null {
  if (body === null || typeof body !== "object") return "Invalid request body.";
  const b = body as Record<string, unknown>;
  if (b.user_position !== "av_at_fault" && b.user_position !== "not_at_fault") {
    return "Invalid position.";
  }
  if (typeof b.user_argument !== "string" || b.user_argument.trim() === "") {
    return "An argument is required.";
  }
  if (b.user_argument.length > MAX_ARGUMENT_CHARS) return "Argument too long.";
  const transcript = b.transcript ?? [];
  if (!isMessageArray(transcript)) return "Invalid transcript.";
  const capErr = transcriptCapError(transcript);
  if (capErr) return capErr;
  const userRounds = transcript.filter((m) => m.role === "user").length;
  if (userRounds >= MAX_ROUNDS) return "Maximum rounds reached.";
  return null;
}

export function judgeCapError(body: unknown): string | null {
  if (body === null || typeof body !== "object") return "Invalid request body.";
  const transcript = (body as Record<string, unknown>).transcript ?? [];
  if (!isMessageArray(transcript)) return "Invalid transcript.";
  return transcriptCapError(transcript);
}

export const BUDGET_MESSAGE =
  "AI debates are taking a break — try again later.";

// Forward a validated request to the internal api and map upstream statuses to
// sane client responses. API_URL never reaches the client — it's read here in
// server-only code and used only to build the fetch URL.
export async function proxyDebate(
  path: string,
  body: unknown,
): Promise<Response> {
  let upstream: Response;
  try {
    upstream = await fetch(`${apiUrl()}${path}`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        ...internalSecretHeaders(),
      },
      body: JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { error: "The debate service is currently unavailable." },
      { status: 502 },
    );
  }

  if (upstream.status === 429) {
    return Response.json({ error: BUDGET_MESSAGE }, { status: 429 });
  }
  if (upstream.status === 404) {
    return Response.json({ error: "Incident not found." }, { status: 404 });
  }
  if (!upstream.ok) {
    // Collapse upstream 5xx to 502; pass through other 4xx as a 400.
    const status = upstream.status >= 500 ? 502 : 400;
    return Response.json(
      { error: "The debate request could not be processed." },
      { status },
    );
  }

  const data = await upstream.json();
  return Response.json(data);
}
