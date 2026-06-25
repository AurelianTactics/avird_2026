import type { Metadata } from "next";
import OntologyGraph from "./OntologyGraph";
import graph from "./graph-data.json";

export const metadata: Metadata = {
  title: "Ontology · avird-2026",
  description:
    "A property-graph ontology built over NHTSA AV crash narratives: schema, real extracted incidents, the pipeline, and takeaways.",
};

const STEPS: { title: string; body: string }[] = [
  {
    title: "Seed the schema from columns",
    body: "A deterministic draft built from the structured SGO fields — Incident, Vehicle, Company, Location, EnvironmentalCondition and their relationships. No LLM, fully reproducible.",
  },
  {
    title: "Discover concepts in narratives",
    body: "An LLM reads the free-text incident narratives and proposes new node and relationship types (Pedestrian, TrafficControl, Maneuver…), each annotated with how many narratives it appeared in.",
  },
  {
    title: "Human edits & freezes the schema",
    body: "Human review the drafts, add competency questions, and save it as schema/v001.yaml. Frozen schemas are never edited in place — revisions become v002 and imply a graph rebuild. To do is to work an LLM into this step for faster and hopefully better iteration.",
  },
  {
    title: "Extract a graph per incident",
    body: "A LangGraph extractor turns each narrative into entities and relationships constrained to the schema. Output is validated, content-addressed-cached JSONL.",
  },
  {
    title: "Project into Neo4j",
    body: "An idempotent batched MERGE loads the artifact into AuraDB. The graph is rebuildable from the JSONL in one command — it is never the source of truth.",
  },
  {
    title: "Evaluate against a golden set",
    body: "Hand-labeled dev and held-out splits score extraction and entity consolidation. Prompts are iterated against dev only; held-out is final-numbers-only.",
  },
];

type Stat = { n: string | number; k: string };

function buildStats(): Stat[] {
  const run = graph.stats.run ?? ({} as Record<string, never>);
  const counters =
    (run as { counters?: Record<string, number> }).counters ?? {};
  const llm = (run as { llm_stats?: Record<string, number> }).llm_stats ?? {};
  const statuses =
    (run as { statuses?: Record<string, number> }).statuses ?? {};
  const pair =
    (graph.stats.consolidation as { pairwise?: Record<string, number> })
      ?.pairwise ?? {};
  return [
    { n: statuses.ok ?? "—", k: "incidents extracted" },
    { n: statuses.skipped_redacted ?? 0, k: "skipped (PII-redacted)" },
    { n: counters.hallucination ?? "—", k: "hallucinations caught" },
    { n: counters.pattern_violation ?? "—", k: "pattern violations dropped" },
    { n: llm.llm_calls ?? "—", k: "LLM calls" },
    { n: pair.f1 ?? "—", k: "consolidation F1" },
  ];
}

export default function OntologyPage() {
  const stats = buildStats();
  const cqs = graph.schema.competency_questions ?? [];
  const counts = graph.schema.counts;
  const gen = graph.generated_from;
  const model =
    (graph.stats.run as { model_id?: string } | undefined)?.model_id ??
    "an LLM";

  return (
    <main>
      <h1>An ontology over AV crash narratives</h1>
      <p className="onto-lede">
        NHTSA&apos;s Standing General Order publishes autonomous-vehicle crash
        reports as structured columns and free-text incident
        narratives. This is a property-graph ontology built over both a
        deterministic backbone seeded from the columns, extended with concept
        types an LLM discovered in the narratives. The LLM then used both elements to extract a graph
        from each incident. Below is the schema, real extracted incidents, how
        the pipeline runs, and some misc thoughts.
      </p>

      <section className="onto-section">
        <h2>Explore the graph</h2>
        <p className="muted">
          {counts.node_types} node types · {counts.relationship_types}{" "}
          relationship types · {counts.patterns} connection patterns. In the
          schema view, node size tracks how often a type appeared in narratives.
          Switch to <em>Real incidents</em> to see graphs extracted from
          individual crash reports.
        </p>
        <OntologyGraph />
      </section>

      <section className="onto-section">
        <h2>How the pipeline works</h2>
        <p className="muted">
          Six stages, each a flat module under <code>ontology/</code>. The
          extraction JSONL is the source of truth; Neo4j AuraDB for storage.
        </p>
        <ol className="onto-steps">
          {STEPS.map((s) => (
            <li key={s.title}>
              <strong>{s.title}</strong>
              <span>{s.body}</span>
            </li>
          ))}
        </ol>
      </section>

      <section className="onto-section">
        <h2>This run, by the numbers</h2>
        <div className="onto-stats">
          {stats.map((s) => (
            <div key={s.k} className="onto-stat">
              <div className="onto-stat__n">{s.n}</div>
              <div className="onto-stat__k">{s.k}</div>
            </div>
          ))}
        </div>
        <p className="muted">
          Model: <code>{model}</code>. Hallucinations and pattern violations are
          caught and dropped by the extractor, not silently kept — they are the
          cost of using an LLM, made visible.
        </p>
      </section>

      <section className="onto-section">
        <h2>Example Questions for Evaluating the Schema (Backlog item is to improve this process with LLM feedback and improved human workflow)</h2>
        <ul className="onto-cqs">
          {cqs.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </section>

      <section className="onto-section">
        <h2>Thoughts</h2>
        <p>
          I have worked on ontologies professionally and here as an experiment.
          I find the ontology process a bit less precise than other aspects of data science work.
          There are many decisions that I can see being done in different ways and are hard to tell which method is better than the other.
          For example, should these similar nodes be merged into one name? And if so which one? Should that be a property or its own node?
          Should there be multiple edges or consolidate with properties?
        </p>
        <p> 
          I tried with this pipeline to address two of my main frustrations with ontology building.</p> 

        <p>1. More metrics based to instrument parts of the pipeline and potentially address weak spots.</p> 
        <p>2. Include an LLM more to review work and help draft initial work.</p> 

        <p> Both approaches had some successes and ares of improvements. The LLM can be helpful in instances but the LLM lacks context
          and can overly prune schemas, not merge properly, or come up with poor examples. The metrics can help with parts but the metrics
          are only as good as the underlying data set and human annotations, which can be a lot of work. Also the sheer magnitude of metrics
          is a bit overwhelming for a simple learning example.
        </p>
      </section>

      <p className="muted onto-provenance">
        Generated from <code>{gen.schema}</code> ({gen.schema_version}) and{" "}
        <code>{gen.artifact}</code> via{" "}
        <code>ontology/export_web_graph.py</code>. Interactive graph rendered
        with vis-network.
      </p>
    </main>
  );
}
