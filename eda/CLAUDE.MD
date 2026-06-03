# EDA
Simple EDA directory. Some human written and some AI coding aided. This file is a
thin index — read the linked `context/` files **on demand**, only when the task
needs them.

## Running code
Python deps live in shared `uv` envs outside the repo. The **main env** is Python
3.14 and lacks LightGBM / SHAP / spaCy wheels; two **Python 3.12 sidecars** carry
those.

```bash
# main env (general EDA: pandas, numpy, matplotlib, sklearn)
source ~/claude_code_repos/my-uv-envs/avird-2026-eda/.venv/Scripts/activate
# LightGBM + SHAP (target modeling, the report notebook)
source ~/claude_code_repos/my-uv-envs/avird-2026-eda-target/.venv/Scripts/activate
# spaCy + en_core_web_lg
source ~/claude_code_repos/my-uv-envs/avird-2026-eda-spacy/.venv/Scripts/activate
```

LightGBM / SHAP / spaCy are lazy-imported inside functions, so on the main env an
import only fails when you call the function — switch to the right sidecar first.

## When asked to do EDA
General preference is to add a function to a new or existing `eda_utils_x.py`:
1. Create a new `eda_utils_x.py` file at the base of this directory, **or**
2. If an `eda_utils_x.py` file is in your context and below 1000 lines, add the
   function there.

## Context index — read on demand
If the user asks about **X**, read **`./context/Y`**:

- **Column names / dtypes / missingness** → `./context/columns.txt`,
  `./context/column_dtypes.csv`
- **What a column means (data dictionary)** → `./context/data_dictionary.md`
  (full PDF text dump), `./context/data_dictionary.csv` (element/definition rows;
  heuristic — spot-check). Caveat: the dictionary does not distinguish schema
  versions.
- **Common categorical values** → `./context/value_counts/<col>.csv`
- **Prior findings, schema gotchas, pipeline & target decisions, redaction &
  NLP caveats, env notes** → `./context/findings.md` (durable; no volatile
  stats)
- **Point-in-time numbers, charts, and the full "what was and wasn't tried"
  coverage log** → `./ADS_to_2026_03_16/08_eda_report_2026.html` (frozen, dated
  snapshot — the data refreshes, so treat its numbers as point-in-time), or the
  editable source notebook `./ADS_to_2026_03_16/08_eda_report_2026.ipynb`
- **Verify the context is sufficient** → `./context/agent_check.md` (questions an
  agent should answer from this index + context files without opening the PDF or
  a notebook)
- **How the reference files are built / maintained** → `./context/README.md`
