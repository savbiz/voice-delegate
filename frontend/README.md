# Frontend

React renders session status, captions, worker state, recap, sources and timings from the live store. `src/realtime/live.ts` owns WebRTC, HTTP and timers; provider audio flows directly between browser and provider. The scripted demo uses no microphone or provider key.

Use Node.js 24 and the pnpm version declared in `package.json`. From the repository root:

```bash
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
pnpm --dir frontend lint
pnpm --dir frontend build
pnpm --dir frontend test
pnpm --dir frontend test:e2e
```

For Playwright's first setup run `pnpm --dir frontend exec playwright install chromium`. Never run pnpm with the repository root as its project directory.

Set `VITE_API_BASE_URL` to the backend origin, such as `https://voice-delegate-api-production.up.railway.app`, in Vercel Production before building. For local development, `frontend/.env.example` leaves this value empty so requests use Vite’s local proxy to `http://localhost:8000`. Vite substitutes this value at build time, so changes require a new build/deploy. Preview URLs require a deliberately configured backend origin policy; production allows one exact frontend origin.

Vercel's project root is `frontend`, preset Vite, output `dist`, install command `pnpm install --frozen-lockfile`. Keep `vercel.json` CSP `connect-src` synchronized with the real backend hostname. Only public frontend configuration belongs here: provider keys, invitation mappings, quota paths and all backend `VOICE_*` settings belong to Railway/Render.

The invitation entered in the UI authorizes API requests and is retained for that session's cleanup. Do not embed invitations in source code or build variables. Provider-side speech detection is authoritative; local onset detection is a latency optimisation. Transcript gaps are estimates, not measured audio playback latency.

See [architecture](../docs/architecture.md), [API](../docs/api.md), [configuration](../docs/configuration.md) and [deployment](../deployment/README.md).
