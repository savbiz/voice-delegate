# ADR 001: GPT-Live with client delegation

Status: accepted for M1, following the project owner's provider choice.

Context: the goal is an uninterrupted voice conversation while an independently testable worker runs. GPT-Live explicitly separates these responsibilities and supports an application-operated backend.

Decision: use GPT-Live over WebRTC and client delegation. Keep `RealtimeProvider` as an application protocol, with an `OpenAILiveProvider` implementation. Map later task dispatch into the internal `delegate_task(goal, context)` boundary. Do not pretend GPT-Live invokes that exact function schema: delegation metadata identifies a request, while the application assembles context.

Consequences: public-provider events stay inside adapters. M1's `/token` capability returns 501; the supported Live browser setup is server-mediated SDP. Azure parity and mid-session fallback remain M3 work. Realtime remains an alternative adapter when explicit voice-model function schemas are needed.

Sources: [Live overview](https://developers.openai.com/api/docs/guides/live), [client delegation](https://developers.openai.com/api/docs/guides/live-delegation), [WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live).
