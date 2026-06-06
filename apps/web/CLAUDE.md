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

## Notes

- Routes that read `API_URL` must declare `export const dynamic = 'force-dynamic'` and pass `cache: 'no-store'` — see [docs/conventions/stack.md](../../docs/conventions/stack.md#build-vs-runtime).
- `API_URL` is **server-only** (no `NEXT_PUBLIC_` prefix). It must never be bundled into client code.
- **Build loop:** after building or changing a visual page, run `/verify-page <route> [intent]` to *see* it — navigate, a11y snapshot, screenshot, console-error check, compare to intent, iterate. It drives the `playwright` plugin's MCP tools (needs a running `npm run dev` or `WEB_URL`, and `npx playwright install` on first use). The deterministic gate is `/verify-site`; the two-layer model is documented in [docs/conventions/workflow.md](../../docs/conventions/workflow.md#two-layer-page-verification).
