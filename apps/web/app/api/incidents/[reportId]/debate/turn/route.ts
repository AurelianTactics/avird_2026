import { proxyDebate, turnCapError } from "../../../../../lib/debate";

// Reads server-only API_URL via proxyDebate — must run dynamically.
export const dynamic = "force-dynamic";

export async function POST(
  req: Request,
  { params }: { params: Promise<{ reportId: string }> },
) {
  const { reportId } = await params;

  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON." }, { status: 400 });
  }

  const capError = turnCapError(body);
  if (capError) return Response.json({ error: capError }, { status: 400 });

  const b = body as Record<string, unknown>;
  return proxyDebate(`/incidents/${encodeURIComponent(reportId)}/debate/turn`, {
    user_position: b.user_position,
    transcript: b.transcript ?? [],
    user_argument: b.user_argument,
  });
}
