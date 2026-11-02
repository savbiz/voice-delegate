# Session controls

Set `VOICE_SESSION_UI=true` on the backend to enable provider discovery and the audio
activity indicator. Default: false. Existing fixed-adapter operation is unchanged when off.
The selector takes its allowlist from `/api/config`, never from a client model name or URL.
It is locked while a conversation is starting, active or closing. Selection applies only
to a new owned session; existing calls retain their provider.

OpenAI Live and Realtime appear when the OpenAI key is configured. Azure also requires its
endpoint and key. ElevenLabs additionally requires its opt-in flag, agent credentials,
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

Enable `VOICE_COST_ESTIMATES=true` separately for the cost panel. It shows each component,
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
