# Workflow

The compound-engineering substrate: slash commands, hooks, and commit conventions. Lives under `.claude/` and is invoked from any agent session in this repo.

> Populated alongside U2 (slash command + hook) and U6 (verify-site harness). New entries land here whenever a new command or hook is added.

## Slash commands

| Command | Runs | When to use |
|---------|------|-------------|
| `/ship` | `ruff check` and `ruff format --check` over `apps/api` + `tools`, `npm run lint` in `apps/web`, then `pytest` in both Python projects and `npm test` in web. | Before committing — gates on lint + format + tests. Reports pass/fail; you commit manually after green. Tolerates empty test suites. Assumes the shared uv env (see [stack.md](stack.md#local-dev-env)) is on PATH. |
| `/verify-site` | `python tools/verify_site.py --base-url $WEB_URL` (the deployed Next.js URL). | After deploy. Asserts the public site responds 200, internal links resolve, and the placeholder index + About pages render expected text. Non-zero exit on any failure. |

To add a new slash command: drop a `.md` file under `.claude/commands/`, document it here, link it from the root [CLAUDE.md](../../CLAUDE.md) if it's a top-level affordance.

## Hooks

| Event | Matcher | Action |
|-------|---------|--------|
| `PostToolUse` (Edit, Write) | `apps/api/**/*.py` | `ruff format` on the touched file. |
| `PostToolUse` (Edit, Write) | `apps/web/**/*.{ts,tsx}` | `prettier --write` on the touched file. |

Scoped narrowly by path glob to keep the feedback loop tight — `docs/**` edits don't trigger anything.

To add a new hook: extend `.claude/settings.json`. Prefer `PostToolUse` with a tight `matcher` for file-at-a-time edits over a broad `Stop` hook. Document the new entry in the table above.

## Commit style

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`. Common types: `feat`, `fix`, `docs`, `chore`, `refactor`, `test`. The `/ship` command advises but does not enforce the format — the convention is for human readability and a future commit-aware changelog tool.

Examples:

```
feat(web): render API health on placeholder index
fix(api): sanitize DB connection error log
docs(p0): writeup of phase 0 scaffold
chore: bump next from 14.2.0 to 14.2.5
```

## Phase writeups

End-of-phase writeups land in [`docs/writeups/`](../writeups/) — one `pN-<slug>.md` per phase. See [docs/writeups/README.md](../writeups/README.md) for what belongs there.

## Institutional learnings

Patterns and post-incident lessons that should compound across phases land in [`docs/solutions/`](../solutions/). See [docs/solutions/README.md](../solutions/README.md). P0 creates the directory; entries start landing from P1 onward.
