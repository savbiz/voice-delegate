# Glossary

| Term | Meaning in this project |
|---|---|
| Sideband | Server WebSocket control/event connection accompanying browser-to-provider WebRTC audio. |
| Commentary | Bounded worker result sent to the voice provider for narration; it is untrusted data, not instructions. |
| Generation | Monotonically increasing version used to reject obsolete work. Delegation generation changes on new work/cancellation; transport generation changes on fallback. |
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
