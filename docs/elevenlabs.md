# ElevenLabs Agents implementation draft

Status: development-only bootstrap and callback boundary, verified offline. Browser
voice support is not complete and is not available in the UI. GPT-Live remains the
configured default. No ElevenLabs account changes or paid calls have been made.

## Implemented in the draft

- `ElevenLabsProvider.prepare_browser()` mints an SDK WebRTC token at the fixed
  ElevenLabs endpoint. It uses a total deadline (three seconds by default, maximum
  five), a 32 KiB response cap, no redirects, no proxy environment and no retries.
  Provider errors are sanitized. Cancellation propagates.
- A typed bootstrap returns `transport`, `conversation_id` and `token`. It never
  fabricates SDP or assumes an expiry not returned by the provider. Tokens do not
  appear in object representations or logs. The API key stays on the backend.
- `POST /api/sessions/{id}/elevenlabs/bootstrap` requires the existing Origin,
  invitation and session-key checks. One attempt is permitted per session, including
  ambiguous failures. The session stays connecting; a duplicate bootstrap or SDP
  offer receives 409. Responses are `no-store`. Disabled preview returns 501.
- Credential issuance does not establish media ownership or confirm provider close.
  `/close` after an issued bootstrap is therefore unconfirmed. Normal session expiry
  still reclaims backend state, but does not prove the upstream conversation ended.
- `ElevenToolBridge` is a frontend port for a future SDK integration. It captures the
  native call ID from `onIncomingEvent` before the parameters-only callback, permits
  only `delegate_task`, deduplicates IDs, caps calls at 64, caps output at 500 UTF-8
  bytes, and bounds callbacks to 20 seconds even if an extension ignores cancellation.
  It never manufactures user turns or executes worker tools in the browser.

No new SDK dependency is added. The port is tested with deterministic callbacks;
its correspondence with the installed SDK still requires integration verification.
There is no UI switch and no callback admission endpoint yet. The draft must not be
presented as a working ElevenLabs voice provider.

## Development configuration

Existing defaults do not change. To exercise only the bootstrap with a private agent,
configure these privately on a development backend, then restart:

```text
VOICE_ELEVENLABS_ENABLED=true
VOICE_ELEVENLABS_AGENT_ID=agent_<your-private-agent>
ELEVENLABS_API_KEY=<set privately in the process environment>
```

`VOICE_ELEVENLABS_TIMEOUT_SECONDS` defaults to 3. Production rejects the preview flag
until lifecycle controls and acceptance are implemented. Do not configure these on
Railway or Vercel for this draft. The frontend never receives `ELEVENLABS_API_KEY`.
Setting the flag does not select ElevenLabs as the current voice provider; the UI
still follows the existing configured provider. The issued credential is sensitive
and may permit chargeable usage if supplied to an SDK; no live bootstrap is required
for the tests below.

A failed bootstrap does not automatically start GPT-Live or retry ElevenLabs. Close
the failed application session, then explicitly create a new session with the existing
provider. Never use a cross-vendor fallback midway through a conversation.

## Remaining before browser voice support

1. Install and pin the official browser SDK, inventory its dependencies/licences and
   review exact signaling/media/worklet hosts for CSP and native restrictions.
2. Wire typed negotiation into the frontend transport selector and preserve cleanup,
   microphone consent, recording choices, audio timing and accessible state handling.
3. Add the owned callback admission and bounded delivery transport. The browser must
   not be able to choose another session, principal or tool registry.
4. Verify private-agent configuration: exactly one tool, `delegate_task`; disable
   browser overrides that bypass policy; bound upstream call duration independently
   of credential expiry and backend heartbeats.
5. Resolve spoken pending-result delivery and server-initiated close. The documented
   SDK tool result can block conversation while it waits. A contextual update does
   not itself trigger a spoken response; a synthetic user message is not an acceptable
   substitute for application-result delivery. Do not claim parity before resolving
   and measuring these behaviors.
6. Test complete lifecycle and delivery offline, then obtain explicit authorization
   for bounded paid acceptance. No audio latency is measured by bootstrap tests.

## Verification

`uv run pytest backend/tests/test_elevenlabs.py` exercises credentials, response caps,
errors, deadline, cancellation, session ownership, duplicate setup and default-off
behavior with HTTP fakes. `pnpm test` from `frontend/` covers the callback port.
These are offline contracts, not proof of SDK interoperability or live quality.

## Public references

- [JavaScript SDK](https://elevenlabs.io/docs/eleven-agents/libraries/java-script)
- [Conversation token API](https://elevenlabs.io/docs/api-reference/conversations/get-webrtc-token)
- [Client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools)
- [SDK source](https://github.com/elevenlabs/packages/blob/main/packages/client/src/BaseConversation.ts)
- [Transport evaluation](elevenlabs-transport.md)
