# apps/web

Next.js (App Router, TypeScript) frontend for avird-2026. The only public origin of the deployed system. Server-side fetches `apps/api`'s `/health` over Railway's project-internal network and renders the result on the placeholder index. See [docs/conventions/stack.md](../../docs/conventions/stack.md).

P0 ships two pages:

| Path     | Purpose                                                    |
|----------|------------------------------------------------------------|
| `/`      | Placeholder index. Renders `API: ok | down | unreachable`. |
| `/about` | About this project. Static text.                           |

## Local dev

```bash
npm install
cp .env.example .env.local        # then point API_URL at your local FastAPI
npm run dev                       # http://localhost:3000
```

## Tests

```bash
npm test          # vitest run, jsdom environment
```

The index test mocks `fetch` to exercise the three states the harness asserts on (`ok`, `down`, `unreachable`).

## Lint + format

```bash
npm run lint
npm run format
```

## Deploy (Railway)

Manual one-time setup:

1. **Create the service.** In the avird-2026 Railway project, add a service from this repo with **root directory = `apps/web`**.
2. **Attach the public domain.** This is the only service in the project that should have one.
3. **Wire `API_URL`.** In this service's variables, add a Railway reference variable pointing at the `api` service's **internal** hostname. Do not paste a literal URL.
4. **Build + start commands** are auto-detected from `package.json`: `npm run build`, `npm run start`.
5. **Verify.** Hit the public URL — the index should render `API: ok` once `apps/api` is also deployed and reachable. The `/verify-site` slash command (U6) automates this check.

## Conventions

- Routes that read `API_URL` declare `export const dynamic = 'force-dynamic'` and pass `cache: 'no-store'` to `fetch`. Without these, Next prerenders the index at build time and bakes "API: unreachable" into the bundle (Railway reference variables are populated at request time, not build time).
- `API_URL` has no `NEXT_PUBLIC_` prefix — it's server-only and must never be bundled into client code.
- The index renders one of three exact strings — `API: ok`, `API: down`, `API: unreachable`. The `/verify-site` harness asserts on these substrings; updates to the index need a corresponding update to the harness's expected-text config.
