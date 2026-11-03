# Session cost estimates

Cost accounting is enabled by default; no environment variable is needed.
The former `VOICE_COST_ESTIMATES` flag is ignored by the application loader. No extra API calls,
credentials or account-wide billing access are needed. The owned heartbeat returns `costs`; close returns
a final snapshot. The frontend shows the estimate in the standalone “Session estimate” panel above the
transcript, including after stop.

The bundled `backend/src/voice_delegate/prices/2026-11-02.json` records its date, version,
source URLs and USD assumptions. `VOICE_PRICE_FILE` can select a local JSON file with the
same schema; it is validated at startup and copied into each session ledger. Restart the
backend to change rates. No prices are fetched at runtime. Keep account-specific files
outside Git and avoid secrets: the file needs only numeric tariffs and public source URLs.

| Component | Counter | Bundled assumption |
| --- | --- | --- |
| GPT-Live | Observed connected seconds, including close wait | $0.05/minute, divided by 60 |
| Worker | Successful response usage: input, cached input, output tokens | GPT-6 Luna: $0.10 / $0.01 / $0.50 per million |
| Decisions | Reported input tokens; cancellation and planner decisions | $0.10 per million; input-only assumption |
| Tavily | Basic search attempts, including failed requests | $0.008/search PAYG; free credits/discounts excluded |
| Realtime, Azure, ElevenLabs | Observed connected seconds | Unpriced; configure an explicit account-specific per-second assumption |

Realtime audio token billing is not a published per-second tariff. A missing voice/model
rate or missing/ambiguous token usage makes the result **partial**, not zero-cost. Failed or
cancelled external requests may still be billed; they increment attempt counts and mark
usage uncertain. Remote workers return numeric usage on terminal results; an interrupted
or ambiguous remote call marks the estimate partial. No conversation text is attached to
usage. Older remote workers without usage reporting are partial. Configure the same worker
model on the backend and private worker: token prices follow that configured model, not
a billing lookup of the remote account. Deterministic offline work records no paid model usage.

These are estimates, not invoices or spending caps. They exclude provider rounding,
cache writes not reported separately, tax, discounts, minimum subscriptions, free credits,
and usage after unconfirmed closure. Backend control attachment approximates connection
time; it cannot observe every upstream audio billing second. Do not use this counter for
billing users. Existing admission quotas and expiry remain the enforcement mechanisms.

Counters are scoped to each session with context-local sinks for concurrent tasks. Repeated
heartbeats and close calls do not duplicate usage; aggregate OTel counter
`voice.session.estimated_cost` has only a fixed `component` label. The Grafana cost panel
sums this metric. It contains neither session/invitation IDs nor conversation content.

## ElevenLabs reported usage

During the existing conversation-close status request, the backend reads only numeric
`metadata.cost` credits, `metadata.cost_fiat` USD and
`metadata.charging.voice_surcharge_charge` when the provider returns them for the matching
agent and conversation in a terminal state. The voice surcharge is separate: ElevenLabs
states it is not included in `cost`. Credits are not converted to dollars. The UI displays
these provider-reported values separately from the estimated total to avoid double counting
an operator-configured voice tariff. No transcript is forwarded or stored by this accounting
path; the existing response-size and timeout bounds still apply.

No additional polling or billing endpoint is introduced. A processing response, delayed usage,
malformed metadata, missing field, permission error or response exceeding the existing size
limit leaves reported usage unavailable; it never becomes an invented zero. A reported zero
is displayed as zero. This first version does not refresh usage after the session is removed,
so credits that arrive later remain available only in ElevenLabs. These values are not an
account invoice or a spending cap.

Sources: [conversation details](https://elevenlabs.io/docs/api-reference/conversations/get),
[metadata schema](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/conversation_history_metadata_common_model.py),
[charging schema](https://github.com/elevenlabs/elevenlabs-python/blob/main/src/elevenlabs/types/conversation_charging_common_model.py).

## Verification

Offline tests cover arithmetic, cached tokens, unknown tariffs, failed calls, concurrent
sink isolation, immutable final voice duration, default-on and disabled modes, bounded provider receipts, remote usage propagation and
owned heartbeat/close payloads. Live reconciliation against provider invoices is pending.
