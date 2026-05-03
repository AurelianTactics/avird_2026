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
