# Glossary

| Term | Meaning in this project |
|---|---|
| Sideband | Server WebSocket control/event connection accompanying browser-to-provider WebRTC audio. |
| Commentary | Bounded worker result sent to the voice provider for narration; it is untrusted data, not instructions. |
| Generation | Monotonically increasing version used to reject obsolete work. Legacy delegation generation changes on new work/cancellation; intent-mode cancellation generation changes only on cancellation. Transport generation changes on fallback. |
| Lease | Durable admission record reserving an active session slot until release or expiry. It is not ownership of the provider connection. |
| Sealed segment | Transcript text committed for fallback replay. Reconnect seals remaining in-flight text before clamping history. |
| Principal | Stable pseudonymous invitation name, hashed before quota/feedback storage. It does not establish a verified human identity. |
| Delegation ID | Provider request identifier used for deduplication and correlating one worker result. |
| Ownership key | Random application session capability sent in `X-Session-Key`; required alongside the invitation. |
| Unconfirmed finalization | Local resources were released without proof that every upstream call closed. Provider usage may continue. |
| Reconnecting | Retained application session awaiting its one configured fallback attempt after transport loss. |
| Instance prefix | Fixed `a-`/`b-` session ID prefix used by the same-host gateway to route requests to the owning API. It is not authentication. |
| Tombstone | Temporary cancelled-job record that prevents a delayed POST from executing work after cancellation. |
| Busy | Worker capacity was exhausted; the request was not queued or silently retried. |

See [architecture](architecture.md) for flow diagrams and [API](api.md) for wire contracts.

- **Browser time to first audio:** offer dispatch to first remote audio energy during
  active playback. Includes setup and possible user wait; not acoustic latency.
- **Speech-end-to-audio:** last detected local speech energy to a fresh remote playback
  onset after at least 300 ms silence. A threshold-based browser observation, distinct
  from transcript timing and provider-only generation time.

- **Offline stack:** opt-in local containers exercising the session API and remote
  LangGraph worker through a deterministic fake voice provider. It generates no audio
  and supplies no evidence of live provider behavior or voice latency.

- **Pending deliverable:** a bounded worker result retained until fresh audio activity
  indicates silence, or the delivery deadline expires. It still occupies a task slot.
- **Intent cancellation:** opt-in policy that separates interruption of narration from
  cancellation of computation; a selected job can stop without invalidating another.
- **Decider:** typed probability classifier. Its uncertainty or failure preserves work;
  relevance is advisory and cannot independently cancel a task.
