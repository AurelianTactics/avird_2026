# Multi-hop query sandbox

Throwaway scratch for learning multi-hop Cypher. Nothing here is wired into the
pipeline. **Every query below is verified against the actual extracted data**
(`artifacts/extractions/extract-20260618-154522-3ad34f17.jsonl`, 127 ok docs) —
not just the schema's *allowed* patterns. Counts next to each pattern are the
number of such edges in the data, so you know rows come back.

> Earlier draft note: the schema in `v001.yaml` lists every relationship the
> pipeline *may* emit. `extract.py` only produced a subset. "Introspection" =
> checking which labels/relationships actually exist before writing queries.
> Done here by counting the JSONL; in the live DB the equivalents are
> `CALL db.labels()` / `CALL db.relationshipTypes()`.

Gotcha found while verifying: `is_subject_vehicle` is the **string** `"true"`,
not a boolean. Filter with `{is_subject_vehicle: "true"}`.

The actual high-frequency edges (use these to build queries):

```
498  (Incident)-[:INVOLVES]->(Vehicle)
288  (Vehicle)-[:OPERATED_BY]->(Company)        # 261 to Company, 17 to Testdriver
270  (Incident)-[:OCCURRED_AT]->(Location)
255  (Incident)-[:HAD_CONDITION]->(EnvironmentalCondition)
220  (Vehicle)-[:COLLIDED_WITH]->(Vehicle)
169  (Vehicle)-[:SUSTAINED_DAMAGE]->(Damage)
117  (Vehicle)-[:TRAVELING_IN]->(Direction)
101  (Vehicle)-[:EXECUTED_MANEUVER]->(Maneuver)
 86  (Vehicle)-[:CONTROLLED_BY]->(Automateddrivingsystem)
```

---

## 1 hop — a relationship right off the node

**Q: "Which company operates each vehicle?"** One traversal, `Vehicle → Company`.
```cypher
MATCH (v:Vehicle)-[:OPERATED_BY]->(c:Company)
RETURN v.vehicle_key, v.make, c.name
LIMIT 25;
```

**Q: "How many vehicles does each company operate in the dataset?"** Same single
hop, aggregated. This is the kind of thing SQL does just as well (one JOIN +
GROUP BY) — included so the comparison stays honest.
```cypher
MATCH (v:Vehicle)-[:OPERATED_BY]->(c:Company)
RETURN c.name AS company, count(v) AS vehicles
ORDER BY vehicles DESC;
```

---

## 2 hops — pivot through a middle node

**Q: "How often did each company's vehicle collide with another vehicle?"**
Two hops pivoting on the vehicle: `Company ← Vehicle → Vehicle`.
```cypher
MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle)-[:COLLIDED_WITH]->(other:Vehicle)
RETURN c.name AS company, count(*) AS collisions
ORDER BY collisions DESC;
```

**Q: "What maneuvers did each company's vehicles execute?"**
`Company ← Vehicle → Maneuver`.
```cypher
MATCH (c:Company)<-[:OPERATED_BY]-(:Vehicle)-[:EXECUTED_MANEUVER]->(m:Maneuver)
RETURN c.name AS company, m.name AS maneuver, count(*) AS n
ORDER BY n DESC
LIMIT 25;
```
(If `m.name` is null in your load, `RETURN m` to see what property holds the text.)

---

## 3+ hops — a chain across node types

**Q: "In which cities did each operating company have incidents?"**
Three hops, two different "directions" of arrow:
`Company ← Vehicle ← Incident → Location`.
```cypher
MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle)<-[:INVOLVES]-(i:Incident)-[:OCCURRED_AT]->(loc:Location)
RETURN c.name AS company, loc.city AS city, count(DISTINCT i) AS incidents
ORDER BY incidents DESC
LIMIT 25;
```
This is where SQL starts to hurt: it's a 3-JOIN chain, and every hop you add is
another JOIN you have to write and read. In Cypher the path is one line you can
literally trace left to right.

**Q: "Under what weather did each company's vehicles execute a maneuver AND sustain
damage?"** Four edges pivoting on the vehicle and its incident — the kind of
question that's a single readable pattern in Cypher and a tangle of JOINs in SQL:
```cypher
MATCH (c:Company)<-[:OPERATED_BY]-(v:Vehicle)-[:EXECUTED_MANEUVER]->(m:Maneuver)
MATCH (v)-[:SUSTAINED_DAMAGE]->(:Damage)
MATCH (i:Incident)-[:INVOLVES]->(v)-[:CONTROLLED_BY]->(:Automateddrivingsystem)
MATCH (i)-[:HAD_CONDITION]->(ec:EnvironmentalCondition)
RETURN c.name AS company, ec.name AS condition, m.name AS maneuver, count(*) AS n
ORDER BY n DESC
LIMIT 25;
```

---

## Variable-length — when you don't know the hop count

**Q: "Show everything within 2 hops of one incident."** The `*1..2` is the part
SQL can't express without a recursive CTE — and even then it can't return the
path as one object. Run in Neo4j Browser to see the subgraph drawn.
```cypher
MATCH (i:Incident)
WITH i LIMIT 1
MATCH p = (i)-[*1..2]-(n)
RETURN p;
```

---

## Reading these as a demonstration

For each query, count the hops and picture the SQL: roughly one JOIN per hop.
The 1-hop aggregate ties with SQL — say so. The 3-hop city query and the
4-edge weather query are where the graph reads better. The variable-length
query is where SQL effectively can't follow.
