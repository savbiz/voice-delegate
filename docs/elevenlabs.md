# ElevenLabs Agents browser transport and server tools

Status: SDK/media lifecycle and authenticated webhook application contracts are verified
offline. Live audio, provider async speech behaviour and hosted callback acceptance remain
pending. No account configuration or paid provider calls are made by this implementation.

## Configuration

ElevenLabs becomes selectable automatically with complete agent credentials. Configure these
variables on the backend, with actual values supplied privately through the environment:

```dotenv
VOICE_ADAPTER=elevenlabs
ELEVENLABS_API_KEY=<server API key>
VOICE_ELEVENLABS_AGENT_ID=agent_<private agent>
VOICE_ELEVENLABS_WEBHOOK_TOKEN=<independent random token of at least 32 characters>
VOICE_ELEVENLABS_WEBHOOK_URL=https://<public backend>/integrations/elevenlabs/delegate
```

Generate the independent service token locally with
`uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Store the same value
as an ElevenLabs tool-header secret. It is not an invitation, browser session key or
ElevenLabs API key. Never place it in the tool's model-visible arguments, URLs or logs.
No environment file or provider account is created or changed automatically.

The agent already exists in ElevenLabs and owns its voice, language and prompt. The browser
uses default language/style; unsupported overrides and mixed-audio recording are rejected.
Use the same instructions as the other providers so behavior does not drift: print them with
`uv run python -m voice_delegate.prompts` and paste the output into the agent's system
prompt. Match the server settings: `--mode semantic` when `VOICE_DECISIONS_CANCEL=true`,
otherwise the default `--mode intent`; add `--web-search` only when web search is enabled and
the worker is not in `offline` mode, as the server does.

The tool's `goal` is natural language, so ElevenLabs needs a model-backed worker
(`VOICE_WORKER_MODE=openai` or `decisions`, the default when `OPENAI_API_KEY` is set). The
`offline` planner only recognises fixed demonstration phrasings and answers anything else
with "No action was taken". Re-paste after
changing a block in `backend/src/voice_delegate/prompts/blocks/`. The worker owns all
individual tools and limits.

## Required agent tool

Configure exactly one **webhook/server tool**, not a client tool. The backend validates this
configuration before minting a browser token, including referenced tool definitions:

```json
{
  "type": "webhook",
  "name": "delegate_task",
  "description": "Ask the worker for calculations, project documentation or public web results. The answer arrives later; keep talking meanwhile.",
  "execution_mode": "async",
  "interruption_mode": "allow",
  "response_timeout_secs": 120,
  "follow_redirects": false,
  "api_schema": {
    "url": "https://<public backend>/integrations/elevenlabs/delegate",
    "method": "POST",
    "content_type": "application/json",
    "request_headers": {
      "X-Voice-Webhook-Token": {"secret_id": "<stored tool-header secret ID>"},
      "X-Voice-Conversation-Id": {"variable_name": "system__conversation_id"}
    },
    "request_body_schema": {
      "type": "object",
      "required": ["goal"],
      "properties": {
        "goal": {"type": "string", "description": "A self-contained request in the user's words, including every number and detail needed"}
      }
    }
  }
}
```

The validator accepts both the API object/map representation above and the dashboard JSON
editor representation: header entries as a list with explicit types, and body properties as
a list with `id=goal`, `required=true` and `value_type=llm_prompt`. The dashboard root body
`required` boolean is distinct from the required goal property. Duplicate headers, additional
properties and static or dynamic-variable goal sources remain rejected.

The URL must exactly equal `VOICE_ELEVENLABS_WEBHOOK_URL`. The token header must reference
provider secret storage; the conversation header must use the reserved system variable,
not a model-generated owner ID. Header binding authenticates a service request; the backend
also requires an existing, unexpired conversation it minted. Do not share the service token
or this private agent with unrelated applications. The agent must require authentication,
have no active workflow or extra built-in tools, and disable client overrides. A workflow
containing only an isolated start node and built-in tool entries set to `null` are inactive
export placeholders. The API may return both the single tool ID and its expanded definition;
both definitions are validated, including matching service-header bindings.

The provider's maximum conversation duration must not exceed `VOICE_SESSION_TTL_SECONDS`.
Execution plus delivery budgets must fit within 110 seconds. The backend response wait is
115 seconds and provider tool timeout is 120 seconds. Hosting and reverse proxies must allow
that bounded HTTP response duration. Dashboard edits can change provider behaviour after
validation; this check does not lock remote configuration.

Use a single backend instance for this integration unless the gateway routes each webhook
to the instance that owns its conversation. The session registry is process-local: the
round-robin two-instance scaling example can send a webhook to the wrong instance and
return 404. Extending proxy timeouts or sharing the quota database does not solve ownership.

A successful bootstrap does not guarantee that a call starts. For immediate disconnects,
inspect the provider conversation error and distinguish account/key limits from application
admission limits; see [operations](operations.md#elevenlabs-bootstrap-and-immediate-disconnects).
Check [current ElevenAgents pricing](https://elevenlabs.io/pricing/agents) and the workspace
billing dashboard: call-minute allowances and LLM credit charges can be separate, so a
remaining shared credit balance does not alone establish available calling capacity.

## Data flow

```mermaid
sequenceDiagram
    participant B as Browser SDK
    participant A as Backend
    participant E as ElevenLabs Agents
    participant W as Existing LangGraph worker
    B->>A: Owned application session and bootstrap
    A->>E: Validate private agent and mint token once
    A-->>B: Temporary SDK token and conversation ID
    B<<->>E: Direct WebRTC audio
    E->>A: Authenticated async delegate_task webhook
    A->>A: Bind conversation and coalesce exact-goal replay
    A->>W: Background job under existing budgets
    Note over B,E: Async provider conversation can continue; live acceptance pending
    B->>A: Owned transcript/activity reports and heartbeat
    W-->>A: Bounded result and sources
    A->>A: Pending delivery waits for fresh quiet activity
    A-->>E: HTTP result after delivery scheduling
    E-->>B: Provider handles result narration
```

The browser never submits delegations, polls task results or resolves client-tool callbacks.
The `/integrations/elevenlabs/delegate` route is separate from `/api` browser Origin checks.
It rejects browser Origin headers, requires the independent service token, binds the reserved
conversation ID to an active owned session and accepts only a bounded `goal` body. Existing
host validation, IP limits and streamed body limits still apply. Responses are `no-store`;
invalid request bodies are rejected without echoing goal text.

An authenticated provider request can attach the control lifecycle before a browser connected
report arrives. The browser remains the source of transcript and audio-activity observations;
this is not a provider-side authoritative event stream. Missing/stale activity holds delivery
until its normal expiry. The new transport removes the browser from tool request/result
transport, not from media, session liveness or the current silence gate.

## Replay and failure policy

The documented webhook request schema does not establish a native invocation ID forwarded to
this endpoint. Each HTTP response correlates to its own provider request. Backend task IDs are
application UUIDs, never presented as upstream tool-call IDs.

For conservative replay protection, identical stripped goals share one task and cached response
for the whole conversation, including concurrent requests. A later identical request does not
refresh a previous web search or rerun a failed/cancelled job. An intentionally changed request
needs a different goal or a new conversation. This is explicit goal coalescing, not a claim of
provider-native exactly-once execution. Different goals retain independent task IDs and limits.

The connection retains at most 64 call records, allows at most four HTTP waiters per goal and
eight per conversation, and returns results within the 500-byte narration budget. The webhook
returns the actual result or a bounded failure/cancellation message, never only a 202 job-start
acknowledgement. The backend does not retry billable work after ambiguous failures.

An HTTP waiter disconnect or cancellation does not cancel useful worker work or another waiter.
The execution/delivery/session budgets still apply; a repeated request can retrieve a prepared
result. If the provider abandons its webhook, narration may be lost: no separate server push or
automatic replay is assumed. A response-window timeout returns an incomplete notice. Explicit
UI/API/semantic cancellation and session end retain the existing task semantics.

A prepared response is not proof of provider acceptance or finished playback. The UI uses
"Result prepared for ElevenLabs webhook". Browser Stop ends SDK media and requests backend
cleanup. Upstream closure is confirmed only by matching provider conversation status; bounded
agent duration remains required when finalization cannot be confirmed. Cross-vendor fallback,
native clients, preference overrides and mixed browser audio recording remain unsupported.

## Local and live acceptance

Local backend work requires a reachable HTTPS tunnel for ElevenLabs server callbacks. Point
both the tool URL and environment variable at that backend route, include its host in
`VOICE_ALLOWED_HOSTS`, and use the independent stored header token. Do not expose debug/admin
routes or loosen the browser Origin policy. A tunnel/host is an operator choice; none is created
by this PR. No frontend CSP change is needed for server-to-server tool requests.

Offline fakes cover configuration rejection, auth/session binding, body limits, replay,
concurrent tasks, busy response, targeted cancellation, silence-gated delivery, disappearing
waiters, session end and response deadlines. SDK tests verify media/event cleanup and the
absence of client tool handlers or result polling. These do not prove live provider behaviour.

A separately authorized smoke must verify private-agent token setup, continued speech during
an async webhook, two tasks, cancellation, silence delivery, identical-goal replay, real webhook
failure, mute, expiry, closure and deployed HTTPS timeouts. No measured provider latency or
account/plan acceptance is claimed.

Public contracts checked on 2026-11-02:
[webhook tools](https://elevenlabs.io/docs/eleven-agents/customization/tools/webhook-tools),
[webhook configuration schema](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/webhook_tool_config_input.py),
[header bindings](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/webhook_tool_api_schema_config_input_request_headers_value.py),
[system variables](https://elevenlabs.io/docs/eleven-agents/customization/personalization/dynamic-variables),
[SDK](https://elevenlabs.io/docs/eleven-agents/libraries/java-script),
[token API](https://elevenlabs.io/docs/api-reference/conversations/get-webrtc-token).

Personal-key users provide their own API key, private Agent ID and webhook token for each
session; they must configure that agent to use this deployment’s webhook. They do not need
a platform invitation. See [personal-key access](personal-api.md).
