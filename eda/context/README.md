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

## Rebuild
```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-eda/.venv/Scripts/activate
python eda/context/_build_context.py
```

Rebuild after the source CSVs change or when adding a new column to the
`VALUE_COUNT_COLS` list in `_build_context.py`.
