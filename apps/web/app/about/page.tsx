import Link from 'next/link';

export default function AboutPage() {
  return (
    <main>
      <h1>About this project</h1>
      <p>
        avird-2026 is a self-directed learning project over NHTSA&apos;s Standing General
        Order on Crash Reporting — autonomous-vehicle crash data published as
        structured fields plus free-text incident narratives.
      </p>
      <p>
        The site doubles as a portfolio: a place to re-exercise data engineering,
        EDA, and ML on a real public dataset, and to learn agentic systems and RAG
        by building them. The build workflow itself — slash commands, hooks, evals —
        is part of what&apos;s being learned.
      </p>
      <p>Per-phase writeups land under <code>docs/writeups/</code> in the repo.</p>
      <nav>
        <Link href="/">Home</Link>
      </nav>
    </main>
  );
}
