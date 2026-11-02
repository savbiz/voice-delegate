# ElevenLabs transport evaluation

Reviewed against official documentation on 2026-11-01 and 2026-11-02. The Agents
path is selected. The implementation now includes SDK-managed browser media and
owned asynchronous tool callbacks; live acceptance remains pending. The evaluation
is retained as design rationale. No account configuration, paid calls, latency
measurements or deployment changes are claimed. See [implementation status](elevenlabs.md).

## Recommendation and decision gate

Use **ElevenLabs Agents over WebRTC**, with a private agent exposing exactly one
application tool, `delegate_task`. The selected implementation uses a native asynchronous
client-tool callback: the backend admits the task, retains its native call ID and returns
the eventual bounded worker result after the existing silence gate. LangGraph and its
tools remain entirely on the backend. Audio stays out of FastAPI.

The admission-only acknowledgement flow below is retained as an evaluated alternative,
not the selected implementation. A background context update alone does not establish
that a result will be spoken. Live use still needs explicit acceptance of asynchronous
speech, result scheduling and closure limits in [the implementation guide](elevenlabs.md).
Webhook admission remains an alternative when stronger provider-origin evidence is needed.

The standalone Realtime API also supports ephemeral browser credentials. A server audio
relay is therefore **not required just because its transport is WebSocket**. It is a
valid second option, with more browser audio plumbing and a separate unresolved question
about server-side control of the same call.

## Documented transport differences

| Concern | Agents | Standalone Realtime |
| --- | --- | --- |
| Browser media | SDK-managed WebRTC for voice | Direct WebSocket with explicit PCM capture/playback |
| Configuration identity | Private `agent_id`, optionally pinned version | Session configuration with model name |
| Credential | Conversation token | Realtime client secret |
| Credential endpoint | `GET /v1/convai/conversation/token` | `POST /v1/convai/realtime/client_secrets` |
| Browser destination | SDK-negotiated signaling/media endpoints | `wss://api.elevenlabs.io/v1/convai/realtime` |
| Delegation | Configured client tool or webhook tool | OpenAI-compatible function-call events |
| Media format | SDK manages negotiation; do not impose standalone PCM settings | PCM16 at 24 kHz in the documented browser guide |
| Backend audio required | No | No, when using the documented ephemeral flow |
| Same-session backend sideband | Not established by the reviewed SDK/token docs | Not established; server-side SDK connection docs are not yet published |
| Current repo support | Opt-in browser SDK and owned async callbacks; live pending | Not implemented |

Agents voice sessions use WebRTC by default; a private session passes a conversation
token to `Conversation.startSession`. The token API returns `token` and
`conversation_id`; keep the latter as backend-owned correlation data. The API key stays
on the backend. A signed URL belongs to the Agents WebSocket route and must not be
confused with either a WebRTC conversation token or a standalone Realtime client secret.
Sources: [JavaScript SDK](https://elevenlabs.io/docs/eleven-agents/libraries/java-script),
[conversation token API](https://elevenlabs.io/docs/api-reference/conversations/get-webrtc-token).

The standalone API accepts a server-authored initial session, including the function
tool list. Its credential response exposes `value`, `expires_at` and `session`; the
browser receives only the short-lived credential. The guide demonstrates a 600-second
expiry; credential expiry is not proof that an already connected call has ended.
The documented model identifiers are `eleven_realtime_v1_mini` and
`eleven_realtime_v1_max`. Their internal component models are not public, and the guide
describes them as cascaded systems: do not label them fused speech-to-speech models.
Sources: [client-secret API](https://elevenlabs.io/docs/api-reference/conversations/create-client-secret),
[Realtime compatibility guide](https://elevenlabs.io/docs/eleven-agents/guides/openai-realtime-compatibility).

## Mapping the one voice tool

### Admission-only client-tool bridge: evaluated alternative

Register only `delegate_task`, using [the existing parameter schema](delegate_task.schema.json).
That schema declares `goal` as a string; the backend `DelegationInput` model supplies the
8,192-character bound, and SDK admission also limits UTF-8 bytes. Agent configuration and client tool
names must match. Enabling Wait for response lets a returned value enter the agent's
conversation context. Keep that wait limited to admission, not the whole worker job.
Sources: [client tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/client-tools),
[client-tool event envelope](https://elevenlabs.io/docs/eleven-agents/customization/events/client-events).

Alternative flow, not the selected native async callback implementation:

1. Our backend authenticates the invitation, allocates the usual session/lease and mints
   the private agent's token. Bind its provider conversation ID to that owned session.
2. The SDK receives a `client_tool_call` with `tool_name`, `tool_call_id` and parameters.
   Forward only `delegate_task` and validated bounded fields to an owned backend route.
   Verify that the chosen SDK exposes the original call ID; do not silently invent a
   replacement ID that defeats retries/deduplication.
3. Backend admission enforces task count, request limit, session ownership, TTL and
   deduplication before starting the existing runner. Return a small accepted/busy/error
   acknowledgement promptly, associated with that call ID.
4. The SDK completes the short tool wait. The worker keeps running while conversation
   continues. Its eventual result becomes the existing pending deliverable.
5. A bounded owned control channel carries delivery commands to the browser. The browser
   attempts delivery only when user and assistant activity indicate silence. New user
   speech defers the attempt; it does not cancel the backend task.

The browser is a relay, not execution or ownership authority. A caller can fabricate
client events; treat their provenance as client-reported, rate-limit them, and never let
them choose principals, provider credentials, worker implementation or other sessions.
This is a conscious trust tradeoff. The official client-tool guide recommends webhook
tools for server API calls; our proposed exception uses a client bridge for session-owned
job admission, not for executing arbitrary APIs or worker tools in the browser.

### Webhook-tool admission: stronger server-origin path

Agents can call a configured HTTP webhook with bearer/custom-header authentication.
The proposed `delegate_task` webhook would perform the same bounded admission and return
an immediate JSON acknowledgement. It would not hold the HTTP request open while a job
finishes. This avoids coupling task lifetime to a provider tool timeout.
Source: [webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools).

This needs a dedicated authenticated service callback, not a relaxation of `/api` Origin
checks. Verify provider conversation ID and stable call identity against the backend's
minted-session binding. Model-generated JSON cannot select the invitation principal or
job owner. Reserved system variables can help correlation, but their exact binding and
SDK/version behavior must be demonstrated before relying on them for authorization.
Runtime tool callbacks must not inherit an assumed signature scheme from post-call
webhooks. Any service credential is operator-managed, separate from browser invitation
and ownership keys, and never appears in model-visible parameters or logs.

Webhook admission does not by itself provide a channel for asynchronously narrating a
finished job. It still needs a verified result-delivery mechanism, potentially through
the browser. It also adds public callback routing and replay/authentication tests to the
first implementation; the client bridge can be developed locally without a public tunnel.

## Interruption, delivery and confirmation

Set `interruption_mode: allow` for `delegate_task`; the older `disable_interruptions`
boolean is deprecated. Provider barge-in must stop or truncate narration without
invalidating our task portfolio. A provider tool interruption is not evidence of an
explicit user cancellation. Only the existing explicit UI/API cancellation, session end
or enabled semantic cancellation advances the task cancellation counter.
Source: [tool interruptions](https://elevenlabs.io/docs/eleven-agents/customization/tools/tool-configuration/tool-interruptions).

SDK speaking/listening status and transcript callbacks can feed the activity bridge.
Their exact WebRTC behavior, ordering and loss handling require acceptance tests; the
published raw client-event examples describe the WebSocket protocol and cannot alone
prove the SDK's WebRTC callback contract. Do not invent a GPT-Live sideband attach URL.

For **both admission paths**, hold a completed job in the backend portfolio until the
silence window and existing delivery deadline permit an attempt. Preserve the original
goal in its bounded preamble. Recheck cancellation and generation immediately before
delivery, and expire stale results with the existing explicit timeout outcome.

`sendContextualUpdate(text)` adds non-interrupting background context. It does not
guarantee an immediate spoken turn. `sendUserMessage(text)` triggers a user-input response
flow; it must not silently insert a worker result as a real user utterance. If this is
the selected delivery primitive, label it internally as application control, keep it
out of user transcripts/semantic-cancellation input, and validate that silence-gated
delivery survives overlapping speech. Do not add a second model-visible tool to request
delivery. Source: [client-to-server events](https://elevenlabs.io/docs/eleven-agents/customization/events/client-to-server-events).

A synchronous SDK method return is at most client submission. It does not establish
provider acceptance or full playback. Report those states separately; keep a close
unconfirmed unless there is verifiable finalization evidence. Browser loss must cancel
or expire local work and release resources according to existing lifecycle policy, while
provider-side duration controls bound any call the backend cannot directly terminate.

## Standalone Realtime and the relay alternative

The documented browser flow mints the client secret on the backend, then connects
directly to the standalone WSS endpoint. The browser must resample/capture PCM16 at
24 kHz, pace input, buffer output, flush interrupted audio and release audio resources.
OpenAI wire compatibility is not evidence that every optional event or same-call control
feature is supported. Verify tool results, cancellation and server authority explicitly.

If direct browser control cannot meet our trust/lifecycle requirements, a server-owned
WebSocket audio relay is an option, not a proven requirement. It makes FastAPI carry
audio and changes the current privacy boundary. It needs bounded audio queues, chunk
sizes, backpressure, disconnect propagation, credential isolation and recording consent
rules. Compare direct and relayed paths with identical recordings and the
[benchmark method](benchmarks.md). Added relay latency is **not measured**; publish no
millisecond estimate as a result. The current browser harness handles SDP WebRTC, so
either ElevenLabs transport needs its own collector adapter before entering that table.

## Implementation gates after the maintainer's choice

These are requirements for a future implementation, not active Settings fields or routes:

* Add a provider feature flag off by default, with explicit start-of-session selection.
  Keep the existing provider behavior when disabled. Do not use ElevenLabs as an automatic
  cross-vendor fallback that changes voice during a call.
* Extend transport negotiation explicitly. Today `RealtimeProvider.connect` takes an SDP
  offer and returns a connection with a `WebRTCAnswer`; SDK-managed WebRTC and PCM WSS do
  not fit that contract unchanged. Preserve existing adapters, reuse the provider factory,
  and introduce a typed capability/negotiation result rather than fabricating SDP.
* Keep private-agent tool, prompt and model overrides disabled where the browser could
  bypass server policy. Review the configured agent/version before issuing tokens.
  [Overrides](https://elevenlabs.io/docs/eleven-agents/customization/personalization/overrides)
  are provider-controlled security settings, not just UI preferences.
* Match provider maximum conversation duration to the application session budget.
  The [conversation flow configuration](https://elevenlabs.io/docs/eleven-agents/customization/conversation-flow)
  has a separate call-duration setting; token expiry and heartbeat expiry are different.
* Define total request deadlines, frame/body/result caps and bounded queues. Credential
  failure before connection offers the existing configured provider through a new explicit
  start action; failure during a call closes safely and does not replay old jobs.
* Inspect the chosen SDK's license and dependencies before adding it. Review its signaling,
  media and worklet requirements against web/native CSP with an exact host allowlist.
  Do not add wildcard origins or bypass invitation, quota or feedback controls.
* Build deterministic fakes for credentials, tool admission, duplicate calls, busy limits,
  worker completion during speech, silence delivery, explicit cancellation, callback replay,
  missing acknowledgements, browser loss, expiry and unavailable SDK control. Keep existing
  Ruff/mypy/Python and Vitest/Playwright suites green.
* With separate paid-test authorization, verify actual provider events, result narration,
  close confirmation, quotas, browser audio timing, iOS/Android audio and hosted CSP. Until
  then, document offline verification separately from live acceptance.

The selected Agents implementation is documented in [the transport guide](elevenlabs.md).
The official client-tool schema includes `execution_mode=async`, separately from
`expects_response`; the integration requires both asynchronous execution and a returned
result. Application policy and SDK fixtures are verified offline. Actual continued speech,
spoken result scheduling, media quality and finalization remain live pending.
