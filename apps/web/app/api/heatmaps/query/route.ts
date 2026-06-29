// Same-origin proxy for the NL heatmap query (U7).
//
// The client query box posts here instead of calling the internal `api` service
// directly, so `API_URL` (no NEXT_PUBLIC_ prefix) stays server-only and never
// reaches the browser. This handler reads it server-side, rejects over-length
// text before forwarding (the same bound the API enforces), forwards `{text}` to
// FastAPI `POST /derived/query`, and returns its JSON.
//
// On any upstream failure it returns a `fallback`-shaped payload (HTTP 200) the
// client renders as the default — never a 500.

import { NextResponse } from "next/server";
import type { HeatmapQueryResult } from "../../../lib/api";

export const dynamic = "force-dynamic";

const MAX_TEXT = 500;

// 127.0.0.1, not localhost: Node's fetch resolves localhost to ::1 first on
// Windows, and uvicorn binds IPv4 only — localhost silently ECONNREFUSEDs.
// Read at request time (force-dynamic) so the Railway reference var is honored.
function apiUrl(): string {
  return process.env.API_URL ?? "http://127.0.0.1:8000";
}

function emptyMatrix() {
  return { sv_axis: [], cp_axis: [], cells: [] };
}

function fallbackPayload(): HeatmapQueryResult {
  return {
    contact_areas: emptyMatrix(),
    pre_crash: emptyMatrix(),
    applied_filter: {},
    fallback: true,
    message: "Could not reach the query service — showing all incidents.",
  };
}

export async function POST(request: Request): Promise<Response> {
  let text = "";
  try {
    const body = await request.json();
    if (body && typeof body.text === "string") {
      text = body.text;
    }
  } catch {
    text = "";
  }

  if (text.length > MAX_TEXT) {
    return NextResponse.json({ error: "text too long" }, { status: 422 });
  }

  try {
    const res = await fetch(`${apiUrl()}/derived/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json(fallbackPayload());
    }
    const data = (await res.json()) as HeatmapQueryResult;
    return NextResponse.json(data);
  } catch {
    return NextResponse.json(fallbackPayload());
  }
}
