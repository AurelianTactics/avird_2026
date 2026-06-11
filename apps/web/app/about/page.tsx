const REPO_URL = "https://github.com/AurelianTactics/avird_2026";

export default function AboutPage() {
  return (
    <main>
      <h1>About this project</h1>
      <p>
        avird-2026 is a self-directed learning project over NHTSA&apos;s
        Standing General Order on Crash Reporting — autonomous-vehicle crash
        data published as structured fields plus free-text incident narratives.
      </p>
      <p>
        Per-phase writeups land under <code>docs/writeups/</code> in the repo.
      </p>
      <p>
        Source code:{" "}
        <a href={REPO_URL} target="_blank" rel="noreferrer">
          github.com/AurelianTactics/avird_2026
        </a>
      </p>
    </main>
  );
}
