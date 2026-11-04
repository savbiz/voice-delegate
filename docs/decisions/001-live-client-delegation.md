# ADR 001: GPT-Live with client delegation

Status: accepted 2026-09-20

Context: the goal is an uninterrupted voice conversation while an independently testable worker runs. GPT-Live explicitly separates these responsibilities and supports an application-operated backend.

Decision: use GPT-Live over WebRTC and client delegation. Keep `RealtimeProvider` as an application protocol, with an `OpenAILiveProvider` implementation. Map task dispatch into the internal `delegate_task(goal, context)` boundary. Do not pretend GPT-Live invokes that exact function schema: delegation metadata identifies a request, while the application assembles context.

Consequences: public-provider events stay inside adapters. The first `/token` endpoint returns 501; the supported Live browser setup is server-mediated SDP. Azure and Realtime adapters now share a WebRTC implementation with one explicit fallback attempt. `OpenAIRealtimeProvider` is implemented alongside `OpenAILiveProvider` and `AzureRealtimeProvider`. Adapter capabilities determine supported fallback; [ADR 006](006-fallback-history.md) defines reconnect and replay.

Sources: [Live overview](https://developers.openai.com/api/docs/guides/live), [client delegation](https://developers.openai.com/api/docs/guides/live-delegation), [WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live).

Amended 2026-11-04: the OpenAI and Azure Realtime adapters were removed in 0.3.0. GPT-Live
on OpenAI and on Azure (`AzureLiveProvider`) are the supported WebRTC adapters; ElevenLabs
Agents uses its own transport. Fallback remains one explicit attempt to Azure Live.
