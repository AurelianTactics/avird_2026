"use client";

import MatrixGrid from "./MatrixGrid";
import type { HeatmapMatrix } from "../lib/api";

// Pre-crash movement co-occurrence (R13). One (SV movement, CP movement) pair per
// incident; axes are ordered most-common-first by the API.
export default function PreCrashMatrix({ matrix }: { matrix: HeatmapMatrix }) {
  return (
    <section className="heatmap-section">
      <h2>Pre-crash movements</h2>
      <p className="muted">
        What the subject vehicle (rows) and the other party (columns) were doing
        just before the crash. Darker cells are more common pairings.
      </p>
      <MatrixGrid
        matrix={matrix}
        rowLabel="SV"
        colLabel="CP"
        emptyMessage="No pre-crash movement pairs for this selection."
      />
    </section>
  );
}
