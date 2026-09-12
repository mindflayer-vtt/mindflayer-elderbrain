# Elderbrain setup

Nuxt 4, Vue 3, TypeScript and Nuxt UI implement the appliance administration UI.
Nitro serves the existing configuration, Foundry, controller and management APIs.

Use Node 24.11 or newer (or Node 26):

```sh
npm ci
npm run dev
npm run lint
npm test
npm run build
npx playwright install chromium
npm run test:browser
```

Production uses `node .output/server/index.mjs` with `PORT=8080`.
The multi-stage Dockerfile builds Nuxt and copies only its standalone output.
Existing `STATE_DIR`, `MANAGEMENT_SOCKET`, `MINDFLAYER_WS_URL`,
`MINDFLAYER_SERVER_IMAGE` and `APPLIANCE_VERSION_FILE` variables are preserved.
Credentials stay on the server and retain mode 0600.

The client-rendered Nuxt UI works at `/` and `/elderbrain/`. Browser API calls and built assets use
the `/elderbrain/` prefix so the IP-based Traefik route works. Explicit server aliases
also accepts direct requests and paths after Traefik strips the prefix.
The healthcheck remains `/health`. Browser tests use the production build with
a prefix-stripping proxy, temporary state, and mock controller/management peers.

Nuxt UI supplies the shared forms, cards, buttons, alerts and notifications.
Icons are bundled locally; no external fonts are requested.
