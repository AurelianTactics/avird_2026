import { judgeCapError, proxyDebate } from "../../../../../lib/debate";

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

  const capError = judgeCapError(body);
  if (capError) return Response.json({ error: capError }, { status: 400 });

  const b = body as Record<string, unknown>;
  return proxyDebate(
    `/incidents/${encodeURIComponent(reportId)}/debate/judge`,
    { transcript: b.transcript ?? [] },
  );
}
