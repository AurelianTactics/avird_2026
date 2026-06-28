"use client";

import { useState } from "react";
import ContactAreaHeatmap from "./ContactAreaHeatmap";
import PreCrashMatrix from "./PreCrashMatrix";
import type { Heatmaps, HeatmapQueryResult } from "../lib/api";

// Client shell: holds the current matrices, drives the natural-language query box
// against the same-origin proxy (U7), and swaps the visuals on success. On a
// fallback it restores the server-rendered default and shows a subtle note — the
// page never breaks on a bad query (plan KTD 1, KTD 5).
export default function HeatmapViews({ initial }: { initial: Heatmaps }) {
  const [views, setViews] = useState<Heatmaps>(initial);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setNote(null);
    try {
      const res = await fetch("/api/heatmaps/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = (await res.json()) as HeatmapQueryResult;
      if (data.fallback) {
        setViews(initial);
        setNote(
          data.message || "Couldn't apply that filter — showing all incidents.",
        );
      } else {
        setViews({
          contact_areas: data.contact_areas,
          pre_crash: data.pre_crash,
          applied_filter: data.applied_filter,
        });
        // The filter resolved but matched no canonical incidents — say so
        // plainly instead of leaving two empty grids that read as "broken".
        const empty =
          data.contact_areas.cells.length === 0 &&
          data.pre_crash.cells.length === 0;
        if (empty && Object.keys(data.applied_filter).length > 0) {
          setNote(
            "No incidents match that filter. Try broadening it or clearing the filter.",
          );
        }
      }
    } catch {
      setViews(initial);
      setNote("Couldn't run that query — showing all incidents.");
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setText("");
    setNote(null);
    setViews(initial);
  }

  const filter = views.applied_filter;
  const filterChips = Object.entries(filter);

  return (
    <div className="heatmaps">
      <dl className="legend" aria-label="What the two parties mean">
        <div className="legend__item">
          <dt className="legend__term legend__term--sv">Subject vehicle</dt>
          <dd className="legend__def">
            the autonomous vehicle reported in the incident (the SGO data calls
            it &ldquo;SV&rdquo;).
          </dd>
        </div>
        <div className="legend__item">
          <dt className="legend__term legend__term--cp">Other party</dt>
          <dd className="legend__def">
            the other road user it crashed with — another vehicle, cyclist, or
            pedestrian (the data calls it the crash partner, &ldquo;CP&rdquo;).
          </dd>
        </div>
      </dl>

      <form className="query" onSubmit={onSubmit}>
        <label className="query__label" htmlFor="nl-query">
          Filter the views in plain English
        </label>
        <div className="query__row">
          <input
            id="nl-query"
            className="query__input"
            type="text"
            value={text}
            maxLength={500}
            placeholder="e.g. only Waymo vehicles in Arizona"
            onChange={(e) => setText(e.target.value)}
          />
          <button className="query__submit" type="submit" disabled={loading}>
            {loading ? "Filtering…" : "Apply"}
          </button>
        </div>
      </form>

      <div className="query__state" aria-live="polite">
        {filterChips.length > 0 ? (
          <p className="query__applied">
            Showing:{" "}
            {filterChips.map(([k, v]) => (
              <span key={k} className="chip">
                {k}: {v}
              </span>
            ))}
            <button type="button" className="query__clear" onClick={reset}>
              Clear
            </button>
          </p>
        ) : (
          <p className="muted">Showing all incidents.</p>
        )}
        {note ? <p className="notice notice--subtle">{note}</p> : null}
      </div>

      <ContactAreaHeatmap matrix={views.contact_areas} />
      <PreCrashMatrix matrix={views.pre_crash} />
    </div>
  );
}
