# ADR 002: Explicit lifecycle ownership and finite budgets

Status: accepted for M1.

Context: a browser can disappear during setup, a provider can stall, and a consumer can fall behind. None should cause unbounded local resource retention or implicit success reporting.

Decision: reserve capacity before setup; accept one offer per session; use absolute and heartbeat deadlines; bound HTTP bodies, socket queues, application events, and control writes. Wait for the final close event while the receiver remains alive. Treat missing finalization as unconfirmed. Never automatically retry a billable session-creation POST.

Consequences: local overload rejects admission and event overload fails the session. Remote cleanup cannot be guaranteed when control cannot be recovered. M1 uses one process; distributed ownership is deferred. The browser owns actual media playback; transcripts alone do not prove audio delivery.

Source: [public session lifecycle](https://developers.openai.com/api/docs/guides/live-conversations). Budget values are project choices documented in architecture.md.
