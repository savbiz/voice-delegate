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

In Live voice, **Voice settings & recording → Connection sounds** enables brief local
ascending/descending tones on confirmed connection and session closure. The preference
is on by default and can be disabled before starting. Tones are generated in the browser without external audio assets and
are not routed into the app's recording graph. Speakers can still leak sound into a microphone;
use headphones when recording. Browser audio restrictions may prevent the cues; visual status
remains authoritative. Page navigation tears down audio without guaranteeing a closing cue.

## Shared UI styles

`src/theme.css` defines semantic colors, spacing, radii and shadows. Change those values
when adjusting the shared visual system; keep component-specific layout in `src/style.css`
and existing Tailwind utilities where useful. No complete CSS migration is required.

`src/components/Button.tsx` provides primary, secondary and danger actions while retaining
native button attributes. Its default type is `button`; form actions explicitly use
`type="submit"`. `ModeTabs.tsx` owns the accessible mode selector and keyboard navigation.
Keep those components at module scope so rerenders preserve component identity.

Playwright checks keyboard navigation, contrast, 44-pixel tab targets and conversation
layouts at 320, 390, 768 and 1100 pixels. These are offline browser checks with fake media;
real microphone, Bluetooth, mobile browser and background behaviour still require device tests.

## Native preview

An opt-in [Capacitor iOS/iPadOS and Android scaffold](../docs/mobile.md) reuses this
frontend with local packaged assets. `VOICE_NATIVE_BUILD=true` and an explicit HTTPS
`VITE_API_BASE_URL` are required for `pnpm native:build` / `pnpm native:sync`.
Native voice additionally requires `VITE_NATIVE_LIVE=true` in a test build and an
explicit backend Origin allowlist. It is off by default. Normal Vercel builds and
existing web voice behaviour remain unchanged. An unsigned iOS Simulator build is
verified, as are Android debug and instrumented-test APK builds. Instrumented tests
were not executed. Launch,
physical-device and store acceptance remain pending; building assets is not an App
Store or Google Play publication.

The opt-in ElevenLabs Agents SDK uses the media signaling host
`https://livekit.rtc.elevenlabs.io` / `wss://livekit.rtc.elevenlabs.io` in addition
to the single application API host. Backend configuration still controls availability;
this CSP allowance does not start a session. Native builds keep their existing
restricted policy and do not support this transport yet.

Optional [session controls](../docs/session-ui.md) expose a server-controlled provider selector,
observed audio activity and a separate cost panel. Flags default off; live/device acceptance
is tracked separately from browser tests.
