# EDA
Simple EDA directory. Some human written and some AI coding aided.

## Running code
Python deps live in a shared `uv` env outside the repo at `~/claude_code_repos/my-uv-envs/avird-2026-eda/`.

```bash
source ~/claude_code_repos/my-uv-envs/avird-2026-eda/.venv/Scripts/activate

```

## When asked to do EDA
General preference is add a function to a new eda_utils_x.py. Either
1. Create a new eda_utils_x.py file at the base of this directory
2. If an eda_utils_x.py file is in your context and below 1000 lines then add that function to that file