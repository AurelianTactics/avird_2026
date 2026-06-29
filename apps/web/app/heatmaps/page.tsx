import { fetchHeatmaps } from "../lib/api";
import HeatmapViews from "./HeatmapViews";

// Reads API_URL at request time — must run dynamically (Railway reference var).
export const dynamic = "force-dynamic";

export default async function HeatmapsPage() {
  const result = await fetchHeatmaps();

  return (
    <main>
      <h1>Heatmaps</h1>
      <p className="muted">
        Two derived views over the canonical crash incidents: which vehicle
        areas tend to make contact, and what each vehicle was doing just before
        the crash. Use the box to narrow both views in plain English — for
        example, &ldquo;only Waymo vehicles in Arizona&rdquo;.
      </p>

      {!result.ok ? (
        <p className="notice">
          Could not load heatmaps. The data service may be unavailable.
        </p>
      ) : (
        <HeatmapViews initial={result.data} />
      )}
    </main>
  );
}
