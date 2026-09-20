# Architecture

## Boundaries

The browser owns microphone capture, WebRTC playback, and display-only captions. FastAPI owns admission, session capability keys, time budgets, and server credentials. The session manager owns exactly one provider connection per application session and is the sole executor of delegation requests. The provider adapter translates public wire events into typed application events. M2 adds a LangGraph worker behind `delegate_task(goal, context)`.

Keeping audio on a direct media connection avoids an application audio hop. A sideband provides server-side authority without routing the microphone through Python. Backend results will enter as commentary, separate from trusted instructions.

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI
    participant S as Session manager
    participant V as GPT-Live
    B->>B: Capture microphone and gather ICE
    B->>A: Create application session
    A->>S: Reserve capacity and ownership key
    B->>A: SDP offer with session key
    S->>V: Create Live session with SDP
    V-->>S: Provider ID and SDP answer
    S->>V: Attach sideband
    S-->>B: SDP answer through FastAPI
    B->>V: Establish WebRTC audio
    V-->>B: session.started and spoken audio
    V-->>S: Sideband transcript and lifecycle events
    alt User ends or deadline expires
        S->>V: session.close
        V-->>S: session.closed
        S-->>B: Finalization status
        B->>B: Release microphone and peer
    else Control channel fails
        S->>S: Bounded cleanup; mark unconfirmed if needed
    end
```

M1 handles an unexpected delegation with a short unavailable commentary linked to the provider delegation ID. No LangGraph package or tool execution is installed until M2. This keeps the milestone boundary explicit.

## Lifecycle

`created → connecting → connected → closing → closed` is application transport state. `connected` means SDP and sideband setup completed; the browser separately waits for `session.started` before displaying voice readiness. A session lock serializes offer and close operations. A duplicate offer returns 409. Closed sessions are removed rather than retained indefinitely. Repeating the internal close is safe; a later HTTP request for an already-removed session returns 404.

A single WebSocket reader receives lifecycle events even while close is waiting. Queue exhaustion ends event consumption with an error rather than dropping delegation or termination messages silently. Graceful finalization may be unconfirmed after overflow or a transport failure. The browser heartbeat maintains liveness; it never resets the absolute session deadline.

## API

All `/api` routes require the configured exact Origin. Session routes also require the configured bearer access code; production startup requires a code of at least 24 characters. CORS allows only the explicit frontend origin. Routes with `{id}` also require `X-Session-Key`.

| Method and path | Meaning |
|---|---|
| `GET /healthz` | Process health; no provider call |
| `POST /api/config` | Report whether a demo access code is required |
| `POST /api/sessions` | Reserve an application session; return ID, key, TTL |
| `POST /api/sessions/{id}/offer` | JSON SDP offer; return SDP answer |
| `POST /api/sessions/{id}/heartbeat` | Refresh browser liveness and return state |
| `POST /api/sessions/{id}/close` | Close and report finalization confirmation |
| `POST /api/sessions/{id}/token` | 501 for GPT-Live; capability boundary for later adapters |

## Resource budgets

| Limit | M1 value | Reason and exhaustion behavior |
|---|---|---|
| Concurrent application sessions | 4, configurable | Bound sockets and spend; admission returns 429 |
| Absolute lifetime | 300 s, configurable | Bound duration-based voice cost; server closes |
| Missing heartbeat | 45 s, configurable | Reclaim abandoned tabs and setup reservations |
| Connect deadline | 20 s, configurable | Bound setup; recovery cleanup can add up to 10 s |
| Graceful close wait | 5 s, configurable | Avoid indefinite shutdown; finalization may be unconfirmed |
| WebSocket close handshake | 2 s | Bound transport cleanup after grace period |
| HTTP request body | 64 KiB | Reject large bodies before JSON parsing, including chunked bodies |
| Sideband frame queue / message size | 16 / 1 MiB | Bound reflected media and event memory |
| Normalized event queue | 64 | Fail on slow consumers rather than accumulate stale work |
| WebSocket write high-water mark | 32 KiB | Backpressure for outbound control messages |
| Commentary write deadline | 2 s | Prevent stuck sends from blocking event handling indefinitely |
| M1 commentary content | 500 UTF-8 bytes | Conservative bound for the fixed unavailable response; M2 uses token accounting |
| Browser captions / timing rows | 6,000 characters per speaker / 20 | Bound DOM memory during long sessions |

WebRTC audio buffers belong to the browser and provider. We do not claim to bound those with a Python queue. M3 must define bounded audio buffers if an audio relay is introduced.

## M2–M4 design commitments

- M2: construct task context from transcripts and application state, not from delegation metadata alone. Keep worker instructions separate from voice instructions. Cancellation suppresses late results and cannot undo already-completed external side effects.
- M3: adapter capabilities determine supported fallback. Reconnect uses a new peer connection, a generation ID, and clamped committed text history. Never replay tool executions blindly.
- M4: application-defined turn spans parent provider and delegation spans. Distinguish signaling TTFB, first observed audio, playback onset, transcript gap, and end-to-end task latency. Recorded fake scenarios test scheduling and limits; a real model is required to evaluate model behavior.

## Sources

Reviewed public documentation on 2026-09-20:

- [GPT-Live WebRTC](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live)
- [GPT-Live sideband](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live)
- [Session lifecycle](https://developers.openai.com/api/docs/guides/live-conversations)
- [Delegation](https://developers.openai.com/api/docs/guides/live-delegation)
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)

Application limits and ownership rules are first-principles design choices, not upstream service guarantees.
