# Session controls

Provider discovery and the audio activity indicator are enabled automatically by the
application loader; no feature flag is required.
The selector takes its allowlist from `/api/config`, never from a client model name or URL.
It is locked while a conversation is starting, active or closing. Selection applies only
to a new owned session; existing calls retain their provider.

OpenAI GPT-Live appears when the OpenAI key is configured. Azure also requires its
endpoint and key. ElevenLabs additionally requires complete agent credentials,
intent-based delegation, compatible webhook deadlines and browser transport. The existing
server default remains visible even before a key is configured; Start still checks voice
availability. No key, agent ID or token appears in the selector.

For ElevenLabs, agent-owned language/style and unsupported mixed-audio recording are
explicitly disabled. Switching provider clears those preferences. No cross-vendor fallback
is offered for an ElevenLabs session; ordinary configured Azure recovery remains available
for OpenAI sessions. Native-client acceptance remains separate.

The speaking indicator describes microphone/remote-stream energy observed in the browser.
It is not speech recognition, acoustic ground truth or the cancellation authority. Provider
speech events continue to control interruption. If analysis is unavailable it says so;
stopping or leaving the session clears the observation.

Cost estimates are enabled by default. The panel shows each component,
price version, missing rates and the final snapshot after stop. See
[cost estimate limitations](cost-estimates.md). Existing task cards retain independent IDs,
worker/delivery timing and targeted cancellation; transcripts remain a chronological chat.
The controls, cost grid and chat use the existing responsive theme without a CSS rewrite.

## Verification

Offline tests cover per-session provider isolation, disabled-mode rejection, configured
allowlists, SDK route scoping, bounded discovery fallback, disabled unsupported controls,
selection locking and final cost retention at a 390-pixel viewport. The same flow uses fake
peers and no paid provider. Actual microphone, playback, device and ElevenLabs live acceptance
remain pending.

## Admission and provider limits

Application daily reservations and provider account credits are independent. An application
429 is not an ElevenLabs credit error. For a targeted administrative reset, see
[reset one invitation’s daily allowance](operations.md#reset-one-invitations-daily-allowance).
A successful bootstrap does not guarantee that the provider accepts the conversation.
ElevenLabs can close immediately with `quota_exceeded`; inspect its conversation error
and account/key limits before buying credits. A finalized cost snapshot is terminal,
not proof of a successful call. Missing provider usage stays unavailable, and a partial
zero-dollar estimate does not establish that the call was free.

## Primary voice workspace

Live voice opens by default. Two peer tabs follow: Offline example (a simulated,
silent walkthrough) and Project documentation (search of bundled project sources).
Neither is presented as a voice-provider mode or a general web search. Native links
support keyboard access, direct `#live`, `#demo`, `#reference` URLs and browser history.
Direct offline examples do not mount the voice workspace or request backend configuration.
The offline stack and native previews with voice disabled keep their offline starting page.
Switching workspaces uses the existing cleanup for voice sessions and demonstration timers.

The API access switch distinguishes invited Platform API sessions from Your API keys.
Personal keys require no invitation and are held only for the session. They also enable
only the personally supplied worker/search credentials; no platform-funded fallback is
allowed. See [personal-key access](personal-api.md). ElevenLabs is filtered from native
provider discovery in both modes; native audio acceptance remains separate.
