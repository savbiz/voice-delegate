# Personal and platform API access

The voice workspace offers two billing sources. **Platform API** keeps the existing
invitation/access-code gate and operator-configured providers. **Your API keys** needs
no invitation and uses only the keys supplied for that session. The default remains
Platform API for existing installations; switching is explicit and locked during a call.

| Service | Personal fields | Use |
|---|---|---|
| OpenAI | API key | OpenAI voice and the model-backed worker when supplied |
| ElevenLabs | API key, private Agent ID, webhook token | Voice through an already configured private agent |
| Tavily | Optional API key | Enables this session's worker web-search tool |
| Azure | Resource key, HTTPS Azure resource origin, deployment name | Azure Live primary or opted-in recovery; deployment defaults to `gpt-live-1` |

ElevenLabs and Azure users can supply an optional OpenAI key for the language-model worker.
Without it, the worker uses the deterministic offline planner, which supports bounded
calculator/documentation commands. It cannot provide the same natural-language planning.
No personal request silently uses a platform OpenAI/Tavily key, Azure recovery, or platform
ElevenLabs agent. Provider quotas and charges remain on the supplied accounts.

## Key lifetime

Keys stay in React memory until submission. They are sent once in the HTTPS session-creation
body and the fields clear after that attempt. They are not written to localStorage,
sessionStorage, cookies, environment files, SQLite, feedback, debug recordings, or prompts.
The backend holds isolated provider clients/settings while that session is alive. Close,
expiry and shutdown dispose those clients and remove the session's references. Refreshing
or starting again requires re-entering keys. This is reference cleanup, not a claim of
cryptographic memory zeroization or control over the browser's own password manager.

The backend necessarily receives the private keys. This is not an end-to-end secret channel
that hides them from the service operator. Use this only with a backend you trust. Outside
loopback development, serve the browser and API over HTTPS. Provider calls use fixed vendor
endpoints; Azure origins use the existing HTTPS/resource-host checks.

When the configured worker execution is remote, each job forwards only its personal OpenAI
and Tavily keys to the authenticated private worker. The worker creates an isolated planner,
never substitutes its platform keys, and discards job key references on completion, failure
or cancellation. Use that channel only on the same host, a trusted private network or TLS.
HTTP is accepted only for loopback, private RFC1918/ULA IPs and the shipped `worker`
compose service name. Other worker hostnames require HTTPS. An older worker without
personal-key support must reject that request rather than ignore it.

The backend still enforces global session capacity, per-client request limits, bounded
worker jobs and session expiry. Personal sessions share the same active capacity leases (using a pseudonymous key-derived
identity) but do not consume platform-funded daily voice reservations. In public-demo deployments,
personal leases are capped at `max_sessions - 1` in the shared transaction, preserving
one platform slot; `max_sessions=1` therefore has no personal slots. No raw provider key
is included in those leases. Their session capability key authorizes heartbeat, tasks and close;
platform sessions still require both ownership and invitation authentication.

Recovery is unchecked by default and requires personal Azure credentials when selected.
Server debug recording is available only with its separate per-session consent checkbox.

## ElevenLabs agent setup

The backend operator must set `VOICE_ELEVENLABS_WEBHOOK_URL` to the public HTTPS
`/integrations/elevenlabs/delegate` URL and restart it before ElevenLabs appears in
personal provider choices. No platform ElevenLabs key is needed for personal access.

Personal access does not create or modify an ElevenLabs agent. Configure a private agent
using the [same webhook contract](elevenlabs.md#required-agent-tool), pointed at this
backend's `/integrations/elevenlabs/delegate` URL. Its secret header must contain the same
webhook token entered in the UI. The other header uses `system__conversation_id`.
The backend checks the agent before issuing the short-lived browser token and accepts
webhooks only for a conversation it owns, with that session's webhook token. Neither the
ElevenLabs API key nor that token is returned to the browser after submission.

ElevenLabs is excluded from native provider discovery in both billing modes. Its native
transport remains unsupported. Multiple API instances still require owner-aware webhook
routing; otherwise use one backend instance.

## Configuration cleanup

New installations use [the minimal template](../config/local.env.template). The normal
application loader ignores these obsolete feature flags:

- `VOICE_COST_ESTIMATES`, `VOICE_SESSION_UI`, `VOICE_INTENT_CANCELLATION`, `VOICE_AUDIO_TIMING`:
  enabled automatically.
- `VOICE_ELEVENLABS_ENABLED`, `VOICE_WEB_SEARCH`: inferred from credentials and worker location.
- `VOICE_FALLBACK_ENABLED`: recovery availability follows Azure configuration; actual use
  requires the per-session checkbox and OpenAI primary.
- `VOICE_NATIVE_CLIENTS`: native origins must be explicitly listed; no extra enable flag.
- `VOICE_DEBUG_RECORDING`, `VOICE_OTEL_ENABLED`: recording availability and OTel are automatic;
  recording still requires session consent.

Model/deployment choices, origins/hosts, proxy trust, invitations, resource budgets, private
worker URL/token, recording directory and optional telemetry exporter endpoints remain available. No key, Railway
variable or existing `.env` is changed automatically. The exhaustive `.env.example` remains
a legacy compatibility fixture; its old off switches no longer describe runtime behaviour.
