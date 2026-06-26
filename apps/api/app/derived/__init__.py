"""Derived & visual views (W5): heatmap aggregations + NL-query agent.

Three live, deterministic-by-default views over the treated canonical rows:

- contact-area heatmap (R12) and pre-crash-movement matrix (R13), served by
  `GET /derived/heatmaps` (default or explicit-param-filtered) and the NL
  `POST /derived/query` agent path;
- redacted-narrative stats (R14), served unfiltered by `GET /derived/redaction`.

The aggregation is reimplemented lean here (plain Python over fetched rows,
JSON out) rather than importing the pandas/matplotlib `eda/` research stack
(plan KTD 2). Natural language maps to a structured, allow-list-validated
filter applied through parameterized queries — never model-authored SQL
(plan KTD 3).
"""
