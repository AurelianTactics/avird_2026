# Workflow

The compound-engineering substrate: slash commands, hooks, and commit conventions. Lives under `.claude/` and is invoked from any agent session in this repo.

> Populated alongside U2 (slash command + hook) and U6 (verify-site harness). New entries land here whenever a new command or hook is added.

## Slash commands

| Command | Runs | When to use |
|---------|------|-------------|
| `/ship` | `ruff check` and `ruff format --check` over `apps/api` + `tools`, `npm run lint` in `apps/web`, then `pytest` in both Python projects and `npm test` in web. | Before committing — gates on lint + format + tests. Reports pass/fail; you commit manually after green. Tolerates empty test suites. Assumes the shared uv env (see [stack.md](stack.md#local-dev-env)) is on PATH. |
| `/verify-site` | `python tools/verify_site.py --base-url $WEB_URL` (the deployed Next.js URL). | After deploy. Asserts the public site responds 200, internal links resolve, and the index + About + Groupings pages render expected text. Non-zero exit on any failure. |
| `/verify-page` | Drives one page through the `playwright` plugin's MCP browser tools (navigate → a11y snapshot → screenshot → console check), compares it to stated intent, and reports a punch list. | While building a visual page. Proves it *looks/behaves* right, iterating until the punch list is clean. Needs a running dev server (or `WEB_URL`) and browser binaries (`npx playwright install`). |
| `/verify-local` | Brings up the seeded local stack (`tools/dev_stack.py up`), drives each changed route through the `/verify-page` perception loop, records evidence (`tools/verify_evidence.py record`) into `.verify/`, then runs `verify_site.py --base-url http://localhost:3000`. | Before ending any turn that touched web pages — it produces the evidence the Stop gate checks. Also any time mid-turn to reproduce a bug or validate a fix against real local data. |

To add a new slash command: drop a `.md` file under `.claude/commands/`, document it here, link it from the root [CLAUDE.md](../../CLAUDE.md) if it's a top-level affordance.

## Three-surface page verification

Pages ship behind three complementary surfaces. The design principle:
**instructions steer, hooks enforce** — anything truly required lives in
deterministic code, not markdown.

| Surface | Command / mechanism | Question it answers | Cost |
|---------|--------------------|---------------------|------|
| **Local build loop** | `/verify-local` (wraps `/verify-page` per route + `verify_site.py` on `localhost:3000`) | Does each changed route *render and behave* right against real local data — layout intact, console clean? Leaves checkable evidence in `.verify/`. | Tokens + a real browser; hot-reload speed; iterate until clean. |
| **Stop-gate enforcement** | `verify_gate.py` Stop hook + `mark_web_pending.py` marker (both thin wrappers over `tools/verify_evidence.py`) | Did the loop actually run? Every page-affecting edit becomes pending debt; ending the turn is blocked until each affected route has fresh passing evidence (content hashes match, screenshot exists). Debt **persists across sessions** until verified or explicitly written off by the user (`pending-clear`). | Token-free, deterministic, unskippable. |
| **Post-deploy gate** | `/verify-site` against the deployed URL | Is the *deployed* site reachable, links live, expected text rendering? The env-fidelity net (prod build, prod data, PG 16). | Token-free; CI-shaped; post-deploy. |

Build a visual page with the `frontend-design` skill, close the loop with
`/verify-local`, let the Stop gate confirm the evidence, then `/verify-site`
gates the deploy. Why this exists: see the incident learning
[agent-shipped-website-without-running-verification-loop](../solutions/workflow-issues/agent-shipped-website-without-running-verification-loop.md).
Token-efficiency evolution (Playwright CLI + Skills on-disk snapshots) and
Chrome DevTools MCP (perf/CWV, W5/W7) are noted in
`.claude/commands/verify-page.md`.

## Hooks

| Event | Matcher | Action |
|-------|---------|--------|
| `PostToolUse` (Edit, Write) | `apps/api/**/*.py` | `ruff format` on the touched file. |
| `PostToolUse` (Edit, Write) | `apps/web/**/*.{ts,tsx}` | `prettier --write` on the touched file. |
| `PostToolUse` (Edit, Write) | page-affecting `apps/web/app/**` files (filter lives in `verify_evidence.pending_add`) | `mark_web_pending.py` appends the file to `.verify/pending.json` — verification debt for the Stop gate. Silent, never blocks, fails open. |
| `Stop` | — (always fires) | `verify_gate.py` runs `verify_evidence.check`: blocks end-of-turn with the exact `/verify-local <route>` commands while any pending route lacks fresh passing evidence; clears satisfied debt on pass. Respects `stop_hook_active` (no block loops); fails open on infrastructure errors, closed on missing evidence. |

Scoped narrowly to keep the feedback loop tight — `docs/**` edits don't trigger anything and never trip the gate.

To add a new hook: extend `.claude/settings.json`. Prefer `PostToolUse` with a tight `matcher` for file-at-a-time edits; a `Stop` hook is reserved for true end-of-turn gates like verification debt. Document the new entry in the table above.

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
