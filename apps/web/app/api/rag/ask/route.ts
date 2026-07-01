// Same-origin proxy for the narrative-RAG ask (P2 web delivery).
//
// The client box posts here instead of calling the internal `api` directly, so
// `API_URL` (no NEXT_PUBLIC_ prefix) stays server-only. This handler reads it
// server-side, rejects over-length text before forwarding (the same 500-char
// bound the API enforces), forwards `{question}` to FastAPI `POST /rag/ask`,
// and returns its JSON.
//
// On any upstream failure it returns a `fallback`-shaped payload (HTTP 200) the
// client renders as "couldn't answer" — never a 500.

import { NextResponse } from "next/server";
import type { RagResult } from "../../../lib/api";
import { internalSecretHeaders } from "../../../lib/debate";

export const dynamic = "force-dynamic";

const MAX_TEXT = 500;

// 127.0.0.1, not localhost: Node's fetch resolves localhost to ::1 first on
// Windows, and uvicorn binds IPv4 only — localhost silently ECONNREFUSEDs.
function apiUrl(): string {
  return process.env.API_URL ?? "http://127.0.0.1:8000";
}

function fallbackPayload(question: string): RagResult {
  return {
    question,
    answer: "",
    cited_incident_ids: [],
    retrieved_ids: [],
    retrieved: [],
    supported: false,
    refused: false,
    iterations: 0,
    fallback: true,
    message: "Could not reach the narrative-search service — please try again.",
  };
}

export async function POST(request: Request): Promise<Response> {
  let question = "";
  try {
    const body = await request.json();
    if (body && typeof body.question === "string") {
      question = body.question;
    }
  } catch {
    question = "";
  }

  if (question.length > MAX_TEXT) {
    return NextResponse.json({ error: "question too long" }, { status: 422 });
  }

  try {
    const res = await fetch(`${apiUrl()}/rag/ask`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...internalSecretHeaders(),
      },
      body: JSON.stringify({ question }),
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(fallbackPayload(question));
    }
    const data = (await res.json()) as RagResult;
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(fallbackPayload(question));
  }
}
