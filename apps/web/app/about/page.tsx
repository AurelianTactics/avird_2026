const REPO_URL = "https://github.com/AurelianTactics/avird_2026";

export default function AboutPage() {
  return (
    <main>
      <h1>About</h1>
      <p>
        This website uses the autonomous-vehicle crash
        data provided by the NHTSA&apos;s
        Standing General Order on Crash Reporting. The primary goal for this project is for me to learn new skills and try new things.
        I hope visitors find some of the data and analysis interesting.
      </p>
      <p>
        <a href="https://www.nhtsa.gov/laws-regulations/standing-general-order-crash-reporting" target="_blank" rel="noreferrer">
          https://www.nhtsa.gov/laws-regulations/standing-general-order-crash-reporting
        </a>
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
