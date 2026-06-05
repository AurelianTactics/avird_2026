# EDA Context

Reusable context for AI-aided EDA so a session does not have to re-derive it.

## Files
- `columns.txt` - one column per line, full SGO ADS dataset.
- `column_dtypes.csv` - column, dtype, n_unique, n_missing.
- `value_counts/<col>.csv` - top-200 value counts (with NaN) for columns useful
  to consolidation / categorical work. Edit `VALUE_COUNT_COLS` in
  `_build_context.py` to add more.
- `data_dictionary.md` - full text dump of the SGO 2021-01 PDF, page by page.
- `data_dictionary.csv` - element / definition rows extracted from the PDF
  tables. Heuristic; spot-check before quoting.
- `findings.md` - **hand-authored** durable findings, decisions, and caveats
  from the EDA phase (schema gotchas, pipeline/dedupe/treatment decisions,
  target choices, redaction & NLP caveats, env notes). Deliberately excludes
  volatile point-in-time statistics; those live in the dated report
  (`../ADS_to_2026_03_16/08_eda_report_2026.html`). Not generated — edit by hand.
- `agent_check.md` - **hand-authored** verification question set. In a fresh
  session an agent should answer these from `../CLAUDE.md` + these context files
  without opening the source PDF or a notebook. Not generated.

## Generated vs hand-authored
`columns.txt`, `column_dtypes.csv`, `value_counts/`, and `data_dictionary.md/.csv`
are **generated** by `_build_context.py`. `findings.md` and `agent_check.md` are
**hand-authored** and are not touched by the rebuild.

## Rebuild
```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-eda/.venv/Scripts/activate
python eda/context/_build_context.py
```

Rebuild after the source CSVs change or when adding a new column to the
`VALUE_COUNT_COLS` list in `_build_context.py`. The rebuild regenerates only the
generated files above; it does not overwrite `findings.md` / `agent_check.md`.
