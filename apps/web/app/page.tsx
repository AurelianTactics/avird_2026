// Routes that read API_URL must run dynamically — Railway reference variables
// are populated at request time, not at image build. See docs/conventions/stack.md.
export const dynamic = 'force-dynamic';

const API_URL = process.env.API_URL ?? 'http://localhost:8000';

type ApiStatus = 'ok' | 'down' | 'unreachable';

async function fetchApiStatus(): Promise<ApiStatus> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: 'no-store' });
    if (!res.ok) return 'unreachable';
    const data = (await res.json()) as { db?: string };
    if (data.db === 'ok') return 'ok';
    if (data.db === 'down') return 'down';
    return 'unreachable';
  } catch {
    return 'unreachable';
  }
}

export default async function HomePage() {
  const status = await fetchApiStatus();
  return (
    <main>
      <h1>avird-2026</h1>
      <p>NHTSA AV crash data — placeholder index for the P0 scaffold.</p>
      <p>API: {status}</p>
      <nav>
        <a href="/about">About</a>
      </nav>
    </main>
  );
}
