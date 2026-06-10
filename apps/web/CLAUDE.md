# apps/web

Next.js (App Router, TypeScript) frontend. Public origin; reads `API_URL` server-side to call the internal `apps/api` service.

For project-wide context (stack, conventions, plans, writeups), see the root [CLAUDE.md](../../CLAUDE.md).

## Local quick-start

```bash
npm install
npm run dev      # http://localhost:3000
npm test         # vitest run
npm run lint
```

## Definition of done (web work)

**Done = fresh passing evidence in `.verify/` for every changed route — observed working, not "tests pass".** The Stop gate enforces this deterministically: every page-affecting Edit/Write is marked pending, and the turn cannot end until `/verify-local` has produced evidence (screenshot + console count + content hashes) for each affected route. Verification debt persists across sessions until verified or explicitly written off by the user.

**Honest blocker separation:** a DB that's down blocks *live-data assertions only*. Render, layout, console-cleanliness, and hydration checks are never excused — pages must show graceful fallbacks, and those fallback states get verified too. Never let a real blocker on one layer excuse skipping an unblocked layer.

Why this exists: [the W1–W2 incident](../../docs/solutions/workflow-issues/agent-shipped-website-without-running-verification-loop.md) — ten units and 71 green tests shipped without a single page ever rendered.

## Notes

- Routes that read `API_URL` must declare `export const dynamic = 'force-dynamic'` and pass `cache: 'no-store'` — see [docs/conventions/stack.md](../../docs/conventions/stack.md#build-vs-runtime).
- `API_URL` is **server-only** (no `NEXT_PUBLIC_` prefix). It must never be bundled into client code.
- **Build loop:** run `/verify-local [routes]` — it brings up the seeded local stack (`tools/dev_stack.py up`; one-time DB setup in [stack.md](../../docs/conventions/stack.md#local-database-seeded-native-postgres--no-docker)), drives each route through the `/verify-page` perception loop (navigate, a11y snapshot, screenshot, console check), records evidence, and runs the deterministic `verify_site.py` gate against `localhost:3000`. For a single page mid-iteration, `/verify-page <route> [intent]` alone works too (record the result with `verify_evidence.py record` when it's a route you changed). The full three-surface model is in [docs/conventions/workflow.md](../../docs/conventions/workflow.md#three-surface-page-verification).
