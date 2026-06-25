"use client";

// The one interactive piece of the /ontology page. vis-network touches the DOM
// (window/canvas), so it is a client component and the library is imported
// lazily inside the effect — never during SSR. Data is the static graph-data.json
// baked by ontology/export_web_graph.py (not a live API call).

import { useEffect, useRef, useState } from "react";
import graph from "./graph-data.json";

type Provenance = "column" | "narrative";

type SchemaNode = {
  id: string;
  label: string;
  group: Provenance;
  value: number;
  discovered: number;
  description: string;
  properties: string[];
};
type InstanceNode = {
  id: string;
  label: string;
  group: Provenance;
  type: string;
  name: string;
  quote: string;
  title: string;
};
type Edge = { from: string; to: string; label?: string; title?: string };

type Mode = "schema" | "instances";

// Minimal shapes for the slice of vis-network we use; the library's own types
// are heavy and unnecessary here, and it is imported lazily (client-only).
type VisDataSet = { get: (id: string) => SchemaNode & InstanceNode };
type VisNetwork = {
  on: (event: "click", cb: (params: { nodes: string[] }) => void) => void;
  destroy: () => void;
};
type VisModule = {
  DataSet: new (items: unknown[]) => VisDataSet;
  Network: new (
    container: HTMLElement,
    data: { nodes: VisDataSet; edges: VisDataSet },
    options: unknown,
  ) => VisNetwork;
};

// Light-theme palette, aligned with globals.css (--accent, --ink, --muted).
const COLUMN = "#1f5fb0"; // seeded from structured columns
const NARRATIVE = "#d98324"; // discovered by the LLM in narratives

const GROUPS = {
  column: {
    color: { background: COLUMN, border: "#15457f" },
    font: { color: "#ffffff" },
  },
  narrative: {
    color: { background: NARRATIVE, border: "#9c5210" },
    font: { color: "#1a1d21" },
  },
};

const BASE_OPTIONS = {
  nodes: {
    shape: "dot",
    borderWidth: 2,
    font: { size: 14, face: "system-ui, -apple-system, Segoe UI, sans-serif" },
  },
  edges: {
    color: { color: "#c4ccd4", highlight: COLUMN, hover: "#9aa4af" },
    arrows: { to: { enabled: true, scaleFactor: 0.55 } },
    smooth: { enabled: true, type: "continuous" },
    font: {
      size: 10,
      color: "#5b6470",
      strokeWidth: 4,
      strokeColor: "#ffffff",
      align: "middle",
    },
  },
  groups: GROUPS,
  physics: {
    stabilization: { iterations: 220 },
    barnesHut: {
      gravitationalConstant: -7000,
      springLength: 130,
      springConstant: 0.04,
    },
  },
  interaction: { hover: true, tooltipDelay: 150, navigationButtons: false },
};

export default function OntologyGraph() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("schema");
  const [incident, setIncident] = useState(0);
  const [selected, setSelected] = useState<
    | { kind: "schema"; node: SchemaNode }
    | { kind: "instance"; node: InstanceNode }
    | null
  >(null);

  useEffect(() => {
    let live = true;
    let network: VisNetwork | null = null;
    setSelected(null);

    (async () => {
      const vis =
        (await import("vis-network/standalone")) as unknown as VisModule;
      if (!live || !containerRef.current) return;

      let nodes: (SchemaNode | InstanceNode)[];
      let edges: Edge[];
      if (mode === "schema") {
        nodes = graph.schema.nodes as SchemaNode[];
        // Labels off on the schema view — 120 edges would be unreadable; the
        // relationship name is in the hover tooltip instead.
        edges = (graph.schema.edges as Edge[]).map((e) => ({
          from: e.from,
          to: e.to,
          title: e.title,
        }));
      } else {
        const inc = graph.instances[incident];
        nodes = inc.nodes as InstanceNode[];
        edges = inc.edges as Edge[]; // few enough to label
      }

      const data = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(edges),
      };
      network = new vis.Network(containerRef.current, data, BASE_OPTIONS);
      network.on("click", (params: { nodes: string[] }) => {
        if (!params.nodes.length) {
          setSelected(null);
          return;
        }
        const node = data.nodes.get(params.nodes[0]);
        if (mode === "schema") setSelected({ kind: "schema", node });
        else setSelected({ kind: "instance", node });
      });
    })();

    return () => {
      live = false;
      if (network) network.destroy();
    };
  }, [mode, incident]);

  return (
    <div className="onto-graph">
      <div className="onto-graph__bar">
        <div className="onto-graph__modes" role="group" aria-label="Graph view">
          <button
            type="button"
            className={mode === "schema" ? "is-active" : ""}
            aria-pressed={mode === "schema"}
            onClick={() => setMode("schema")}
          >
            Schema
          </button>
          <button
            type="button"
            className={mode === "instances" ? "is-active" : ""}
            aria-pressed={mode === "instances"}
            onClick={() => setMode("instances")}
          >
            Real incidents
          </button>
        </div>
        {mode === "instances" && (
          <label className="onto-graph__pick">
            <span className="muted">incident</span>
            <select
              value={incident}
              onChange={(e) => setIncident(Number(e.target.value))}
            >
              {graph.instances.map((inc, i) => (
                <option key={inc.doc_key} value={i}>
                  {i + 1} · {inc.doc_key.slice(0, 7)} ({inc.nodes.length} nodes)
                </option>
              ))}
            </select>
          </label>
        )}
        <span className="onto-graph__legend">
          <span className="onto-dot onto-dot--col" /> from columns
          <span className="onto-dot onto-dot--nar" /> discovered in narratives
        </span>
      </div>

      <div className="onto-graph__stage">
        <div ref={containerRef} className="onto-graph__canvas" />
        <aside className="onto-graph__panel">
          {renderPanel(selected, mode, incident)}
        </aside>
      </div>
    </div>
  );
}

function renderPanel(
  selected:
    | { kind: "schema"; node: SchemaNode }
    | { kind: "instance"; node: InstanceNode }
    | null,
  mode: Mode,
  incident: number,
) {
  if (!selected) {
    const hint =
      mode === "schema"
        ? "Click a type to see its description and properties. Drag to rearrange, scroll to zoom."
        : `Incident ${graph.instances[incident].doc_key} — click any node to inspect the extracted entity.`;
    return <p className="muted">{hint}</p>;
  }

  if (selected.kind === "schema") {
    const n = selected.node;
    return (
      <>
        <h3>{n.label}</h3>
        <span className={`onto-tag onto-tag--${n.group}`}>{n.group}</span>
        <p>{n.description}</p>
        {n.discovered > 0 && (
          <p className="muted">
            Discovered in <strong>{n.discovered}</strong> narratives.
          </p>
        )}
        {n.properties.length > 0 ? (
          <>
            <h4>Properties</h4>
            <ul>
              {n.properties.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">
            No structured properties — a narrative-only concept.
          </p>
        )}
      </>
    );
  }

  const n = selected.node;
  const lines = (n.title || "")
    .split("\n")
    .slice(1)
    .map((l) => l.trim())
    .filter(Boolean);
  return (
    <>
      <h3>{n.name || n.label}</h3>
      <span className={`onto-tag onto-tag--${n.group}`}>
        {n.type} · {n.group}
      </span>
      {lines.length > 0 && (
        <ul>
          {lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      )}
      {n.quote && <p className="muted">“{n.quote}”</p>}
    </>
  );
}
