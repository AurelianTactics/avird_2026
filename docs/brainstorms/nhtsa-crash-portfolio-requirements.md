---
date: 2026-04-27
topic: nhtsa-crash-portfolio
---

# NHTSA AV Crash Data Site — Self-Directed Learning Project

## Problem Frame

A working data scientist wants to (1) re-exercise existing data engineering, EDA, and ML skills on a real, public, non-trivial dataset, and (2) genuinely learn agentic systems and RAG by building them — not by reading about them. The output is a public website that doubles as a learning artifact: a place where future-you can re-read what you built and how, and where anyone who lands on it can see what AV crash data actually says.

Audience is self-first. Polish matters insofar as a year-from-now-you (or a curious visitor) can navigate it without confusion, but no portfolio-comparison pressure shapes scope. The compounding goal is that the build *workflow* (compound engineering: hooks, slash commands, evals, eventually issue→PR agents) becomes its own learnable skill alongside the project content.

Data source: NHTSA Standing General Order on Crash Reporting (https://www.nhtsa.gov/laws-regulations/standing-general-order-crash-reporting). The dataset has both structured tabular fields and free-text incident narratives — that mix is what makes it interesting for both classical ML and modern NLP/RAG/agentic work.

## Phase Map

```
P0 Scaffold    →  P1 Data + EDA  →  P2 Models       →  P3 RAG          →  P4 Fault debate  →  P5 Harness/stretch
empty live      ingestion + DB     severity + TS     narrative chat     3-LLM mediator       issue→PR agent
site, AI-dev    cleaning           experiment        eval set                                deeper hooks/evals
workflow set    dictionary page    tracking          data dict RAG                           site-review harness
up              first plots        AI-augmented dev  site-content RAG

[site live and viewable at the end of every phase]
```

Each phase ends with the site deployed and the new capability visible. IA is emergent — pages may merge or split as the data leads us; do not pre-architect the navigation.

## Requirements

**Project shape & site**
- R1. Site is publicly deployed on Railway from end of P0 onward; every subsequent phase ships visible content or a working interactive feature.
- R2. Stack: Next.js frontend + FastAPI Python service + Postgres, all on Railway. Frontend can be AI-generated since UI implementation is not the learning goal.
- R3. Information architecture is emergent. Pages can be capability-focused, topic-focused, or mixed. Do not commit to a fixed taxonomy upfront.
- R4. Repo conventions land in P0 and remain in force: progressive disclosure CLAUDE.md, slash commands, hooks for lint/format/test, conventional commits, brief writeups committed alongside code.

**Phase 0 — Scaffold**
- R5. Empty Next.js site deployed on Railway with About page and a placeholder index.
- R6. FastAPI service deployed on Railway returning a health route; reachable from the frontend.
- R7. Empty Postgres provisioned; connection wired through env vars; verified end-to-end with one trivial query.
- R8. CLAUDE.md committed with progressive disclosure (top-level summary, deeper docs linked).
- R9. At least one slash command and one hook in place (e.g. format-on-stop, or a `/ship` command that runs lint/test before commit) — establishes the compound-engineering substrate.

**Phase 1 — Data + first EDA**
- R10. NHTSA SGO data ingested into Postgres via a reproducible script; raw + cleaned tables both retained.
- R11. Cleaning pass that handles known-messy fields (date parsing, free-text normalization, sparse outcome fields). Cleaning rules are documented on-site, not just in code.
- R12. Data dictionary rendered as a site page from a single source of truth (JSON or YAML in repo, rendered on the frontend).
- R13. Baseline EDA published to the site: row counts, distributions over key fields, time-of-day/region/company breakdowns, narrative length distribution. At least one chart that answers a real question, not a stock histogram.

**Phase 2 — Models**
- R14. Severity classification: tabular baseline + narrative-NLP variant (e.g. fine-tune or embed-and-classify on incident text). Both reported with the same eval split.
- R15. Time series model for incident counts (aggregate or segmented). Honest holdout, honest baselines (naive/seasonal-naive), explicit acknowledgment of dataset limits.
- R16. Experiment tracking integrated: every model run logs config, metrics, artifacts to a single tracking surface visible on the site (chosen in planning — see deferred questions).
- R17. P2 is the deliberate "AI-tool-augmented" phase: most ML code is written through an AI coding workflow. The site includes a candid writeup of where the tools were genuinely useful vs. where they misled — this writeup is part of the deliverable, not optional.

**Phase 3 — RAG over narratives**
- R18. Narrative corpus indexed with documented chunking + embedding choices.
- R19. "Talk to the data" interactive feature on the site: free-form question → grounded answer with citations back to specific incidents.
- R20. Two additional retrieval surfaces share infrastructure: (a) data dictionary RAG ("what does field X mean"), (b) site-content RAG ("what's on this site / where do I find Y").
- R21. Eval set for retrieval quality (relevance) and answer quality (faithfulness/groundedness). Eval results published.

**Phase 4 — Fault attribution + LLM debate**
- R22. Agent graph that reads an incident report and produces a written fault attribution with reasoning.
- R23. User can argue with the attribution. Two debate modes: (a) user vs. attributing LLM directly, (b) user-aligned LLM vs. attributing LLM with a third LLM as mediator. Mediator returns a final structured judgment.
- R24. Eval set for fault-attribution outputs (does the attribution match a held-out human label set? does it cite the narrative?). Eval results published.
- R25. Cost-aware design: 3-LLM debate is bounded (turn limit, token budget) and the cost per debate is shown to the user.

**Phase 5 — Harness / compound stretch**
- R26. Issue → PR agent: an agent that, given a GitHub issue, proposes a PR against the repo with a real change. Reviewed by hand, not auto-merged.
- R27. Site-review harness: agent that screenshots/audits site pages and produces a punch list of issues (broken links, layout regressions, copy nits).
- R28. Expanded eval coverage: at minimum, regression evals for P3 RAG and P4 fault-attribution that run on a schedule or hook.

## Success Criteria

- A year from now, returning to the repo, you can re-read each phase's writeup and remember not just *what* you built but *why* the choices made sense.
- After P3 you can demo the "talk to the data" feature on a fresh question and get a grounded, cited answer — not a hallucination.
- After P4 you can hand someone a real incident, get a fault attribution, argue with it, and walk away believing the system reasoned about *that* incident, not a generic one.
- After P2 you have written down — publicly on the site — the specific places AI coding tools helped you and the specific places they misled you. This is the test that the "AI-augmented ML" thread actually produced learning, not just throughput.
- The compound-engineering workflow (hooks, slash commands, evals) was useful from P1 onward, not bolted on at the end.

## Scope Boundaries

- **No upfront narrative spine.** Site IA emerges. We will not pick a single anchor question and force every phase to answer it.
- **No "kitchen-sink portfolio" framing.** Audience is self; presentation polish is bounded by "navigable in a year" not "wow a recruiter in 30 seconds."
- **No carry-forward from old iterations.** Clean rebuild, including the fault-attribution + debate prototype.
- **Time series scope is bounded.** One honest forecast at one aggregation level is the bar; we are not building a full forecasting platform.
- **The fault debate is the only multi-agent system in scope through P4.** Multi-agent investigative pipelines, fully agent-native visitor UX, and workflow agents that ship their own work are explicitly out of P0–P4 scope (some return as P5 stretch).
- **No real-time data.** SGO data is ingested as periodic batch refreshes, not streamed.
- **No PII work beyond what NHTSA already redacts.** We do not attempt re-identification or enrichment with personally identifying external data.
- **No auth / accounts** unless a later phase forces it (e.g. cost control on debate). Default is anonymous public access with rate limits.

## Key Decisions

- **Phase 0 exists, even though it wasn't in your original list.** Standing up the empty deployed site + AI-dev workflow first means every later phase compounds on a working substrate. Retrofitting compound engineering after P3 would be expensive.
- **Audience = self-learning, not portfolio.** Polish bounded by "future-me can re-read this," not "stranger judges this in 5 minutes." Frees us from kitchen-sink instincts.
- **Primary learning frontiers = agentic + RAG.** P3 and P4 get the most rigor (real eval sets, honest writeups). P1–P2 ship adequate.
- **Production ML is "redo familiar work AI-augmented."** Not the place to invent technique. The novelty is the workflow, and the writeup of that workflow is part of the P2 deliverable.
- **Stack: Next.js + FastAPI + Postgres on Railway.** Next.js chosen because UI is the kind of code AI tools are good at producing — low marginal cost, high flexibility for agentic UIs. FastAPI keeps Python-centric ML/agent code idiomatic.
- **Headline agentic artifact = fault attribution + 3-LLM debate.** Fun, scoped, evaluable, and uniquely well-suited to the data. Other agentic patterns (multi-agent pipelines, agent-native UX, workflow agents) are deferred to P5 stretch.
- **IA is emergent, not designed.** Pages reorganize as findings come in. The brainstorm explicitly does not pin down site navigation.
- **Ship every phase live.** No "wait till the end" demo. Each phase ends with deployed, viewable progress.

## Dependencies / Assumptions

- NHTSA SGO data is downloadable as CSV (or similar) at the URL above and updates periodically. *Unverified — to confirm at start of P1.*
- Railway supports the three needed services (Next.js, FastAPI, Postgres) on a hobby/pro tier within budget. *Unverified — to confirm at start of P0.*
- Anthropic / OpenAI / etc. API access is available; no air-gap requirement.
- Google Maps Static API (or similar) is acceptable for incident-location images (originally listed as a frontend feature) — deferred to whichever phase actually needs it.
- It is acceptable for the site to be open to the public with rate limits rather than gated behind auth.

## Outstanding Questions

### Resolve Before Planning

- [Affects R17][User decision] What is the **AI tool of record** for the AI-augmented build (Claude Code primary? Cursor? Both alternated deliberately as part of the experiment?). This shapes how the P2 writeup is framed and what we instrument.
- [Affects all phases][User decision] **Pace**: roughly how much time per week, and what's the rough target landing zone for P0–P4? Even a vague answer (e.g. "evenings + weekends, P4 done by late summer") shapes scope cuts vs. expansions.

### Deferred to Planning

- [Affects R16][Technical] Experiment tracking platform: MLflow self-hosted on Railway, W&B free tier, or a custom minimal solution? Decide in P2 planning.
- [Affects R18, R21][Needs research] RAG infrastructure: pgvector on existing Postgres, dedicated vector DB (Qdrant/Weaviate), or a managed service? Decide at start of P3.
- [Affects R22, R23][Needs research] Agent framework: LangGraph, plain orchestration code, or a thinner harness? Decide at start of P4 — there's a real "learn the framework vs. learn the primitives" trade.
- [Affects R23][Technical] How is the visitor's "argue" turn captured — free text? structured rebuttal form? — and how is the mediator's final judgment shown? Decide in P4 planning after we've felt the eval output.
- [Affects R25][Technical] Cost-control mechanics for the fault debate (per-IP rate limit? daily budget circuit breaker? deterministic seeding for cheap replay?). Decide in P4 planning.
- [Affects R13, frontend feature parity][Technical] Google Maps imagery — which phase pulls this in, and at what cost? Likely P1 or P5; decide when a page actually wants it.
- [Affects R26][Technical] Issue → PR agent: harness choice (Claude Code action? GitHub Actions + agent CLI? bespoke?). Decide at P5.
- [Affects R27][Technical] Site-review harness: visual diff vs. agent-judged audit vs. both. Decide at P5.

## Next Steps

`Resolve Before Planning` is non-empty (AI tool of record + pace). These are quick to answer in chat — once they're in, hand off to `/ce-plan` for **Phase 0** only ("plan phase by phase, refactor as the data leads us"). Subsequent phases get their own planning passes when the prior one ships.
