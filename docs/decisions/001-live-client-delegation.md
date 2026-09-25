# ADR 001: GPT-Live with client delegation

Status: accepted, following the project owner's provider choice.

Context: the goal is an uninterrupted voice conversation while an independently testable worker runs. GPT-Live explicitly separates these responsibilities and supports an application-operated backend.

Decision: use GPT-Live over WebRTC and client delegation. Keep `RealtimeProvider` as an application protocol, with an `OpenAILiveProvider` implementation. Map later task dispatch into the internal `delegate_task(goal, context)` boundary. Do not pretend GPT-Live invokes that exact function schema: delegation metadata identifies a request, while the application assembles context.

Consequences: public-provider events stay inside adapters. The first `/token` endpoint returns 501; the supported Live browser setup is server-mediated SDP. Azure and Realtime adapters now share a WebRTC implementation with one explicit fallback attempt.

Sources: [Live overview](https://developers.openai.com/api/docs/guides/live), [client delegation](https://developers.openai.com/api/docs/guides/live-delegation), [WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live).

Implementation status: `OpenAIRealtimeProvider` is implemented alongside `OpenAILiveProvider` and `AzureRealtimeProvider`.

Adapter capabilities determined supported fallback. Reconnect was implemented with a new peer connection, a generation ID and clamped committed text history. Tool executions were excluded from replay.
