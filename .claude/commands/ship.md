---
description: Lint + format + test gate for both apps. Reports pass/fail; user commits manually after green.
allowed-tools: Bash(ruff:*), Bash(npm run lint:*), Bash(npm test:*), Bash(pytest:*), Bash(python -m pytest:*)
---

# /ship

You are gating the working tree before commit. Run each step in order, capture pass/fail per step, and print a final summary. Do **not** commit — that is the user's call once everything is green.

## Steps

Run all steps even if earlier ones fail; collect results and report at the end. Tolerate empty test suites — they are expected in P0.

The Python steps assume the shared uv env at `~/claude_code_repos/my-uv-envs/avird-2026-app/.venv` is activated, or that `ruff`/`pytest` is otherwise on PATH.

1. **Python lint:** `ruff check apps/api tools`
2. **Python format check:** `ruff format --check apps/api tools`
3. **Web lint:** in `apps/web`, run `npm run lint`
4. **Python tests (api):** in `apps/api`, run `pytest`. Treat "no tests collected" as pass.
5. **Python tests (tools):** in `tools`, run `pytest`. Treat "no tests collected" as pass.
6. **Web tests:** in `apps/web`, run `npm test`. Treat exit 0 with zero tests as pass.

## Output

Print a punch list, one line per step, prefixed `[ok]` or `[fail]`, plus a final summary count. If any step failed, exit non-zero (or, when run interactively, end with a clear `not ready to ship` line). On all-green, end with `ready to commit`.

## Commit advice

The repo uses Conventional Commits (`type(scope): summary` — see `docs/conventions/workflow.md`). When advising a commit message, prefer:

- `feat(scope):` for user-visible behavior
- `fix(scope):` for bug fixes
- `docs(scope):` for prose changes
- `chore(scope):` for tooling and config
- `test(scope):` for test-only changes
- `refactor(scope):` for behavior-preserving rewrites

Do not run `git commit` yourself.
