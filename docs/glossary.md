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

A completed task in the optional task portfolio has sent its result to the voice provider;
this does not confirm complete audio playback. Its displayed duration includes the wait for
delivery and freezes at the terminal state. After session end, task rows are last-reported states.

Worker time measures task start to worker result readiness (or cancellation). Delivery wait
measures result readiness to send completion or expiry; it is not provider audio latency.

- **Allowed origins**: exact browser scheme, hostname and optional port values in
  `VOICE_ALLOWED_ORIGINS`. They govern route access and CORS, independently of the
  backend's allowed Host headers. Codespaces may rewrite the browser Origin.

- **Choice question:** a classification over a server-supplied finite list of values,
  with a selected value, confidence and probability distribution. It does not generate
  free-form tool arguments.
- **DecisionsPlanner:** opt-in worker planner that chooses a tool, final answer or
  refusal through the shared Decider. Classification failure uses the existing text
  planner; refusal does not. It is separate from semantic task cancellation.

**Native origin:** the local web origin of packaged Capacitor content:
`capacitor://localhost` on iOS and `https://localhost` on Android. This differs from
both the public website and the backend host; it requires an explicit allowlist.

**Capacitor preview:** the optional iOS/iPadOS and Android container for the React
frontend. Local web-asset verification is separate from native-device and store acceptance.

**Response-onset latency:** time from the labelled end of a fixed input recording to
the first received playback energy, using one browser audio clock. It differs from
transcript arrival, provider setup and acoustic speaker latency.

**Censored benchmark observation:** an attempted case with overlap, timeout, missing
evidence or transport failure. It remains in outcome and accuracy denominators and
does not become a zero-millisecond latency sample.

**Web evidence:** up to three HTTPS sources returned by the opt-in worker search
adapter, identified by canonical URL and clipped to the existing excerpt budget.
It differs from the bundled project documentation and is untrusted input.

**Terminal evidence step:** a web search after which the graph permits a final answer
but rejects additional tool calls. It limits injection-driven tool execution while
leaving semantic answer quality subject to separate evaluation.

**Agents conversation token:** a short-lived credential for an ElevenLabs Agents
WebRTC session associated with a configured agent. The proposed adapter mints it on
the backend; it differs from a standalone Realtime client secret.

**Standalone Realtime client secret:** an ephemeral credential minted against a
server-authored ElevenLabs Realtime session for a direct browser WebSocket connection.
Its expiry is distinct from the lifetime of an established call.

**Client-tool admission bridge:** the proposed path that forwards a voice tool request
from the browser SDK to our owned backend admission logic. It returns an acknowledgement
promptly; the browser does not execute LangGraph worker tools.

**Contextual update:** background information supplied to a provider conversation.
It does not itself prove that a pending result has been narrated or fully played.

**Agents bootstrap preview:** a development-only endpoint returning an SDK WebRTC
token and conversation ID. It reserves one setup attempt on an owned session and
does not imply that media is connected or that upstream closure is confirmed.

- **Agents SDK transport:** optional ElevenLabs WebRTC media with owner-authenticated
  client events and native asynchronous tool-result correlation. It does not expose
  an SDP answer or imply that a browser disconnect confirms upstream finalization.
