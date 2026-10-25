# Decisions cancellation smoke — 2026-10-25

A user-authorized paid test made four sequential requests to `POST /v1/decisions`
using `gpt-6-luna`, the repository's OpenAIDecider, a one-second timeout, no retries,
and cancellation threshold 0.85. No voice session or worker-model call was made.
Inputs were synthetic Italian phrases about a task searching fallback documentation;
no recorded conversation was sent. Each request asked the same cancellation and relevance
predicates used by the task portfolio.

| Case | User phrase | Expected cancellation | Observed outcome | Client elapsed | Cancellation probability | Relevance probability | Reported input tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Continue talking | Intanto raccontami qualcosa. | No | Timeout; preserve work | 1.003 s | — | — | Unavailable |
| Explicit cancellation | Annulla la ricerca che ti ho chiesto. | Yes | Timeout; preserve work | 1.003 s | — | — | Unavailable |
| New topic | Adesso spiegami come funziona il microfono. | No | Success; preserve work | 0.612 s | 0.00 | 0.17 | 376 |
| Keep the task | Non annullare la ricerca, mi serve ancora. | No | Success; preserve work | 0.146 s | 0.00 | 1.00 | 376 |

Two of four requests returned valid answers within the configured deadline. Both successful
answers preserved work as expected. The explicit-cancellation case was not verified.
This tiny smoke is not an accuracy benchmark or evidence of production reliability.
Client elapsed time includes network and connection setup; timeouts do not reveal provider
completion or billing. No additional requests were made after this four-call budget.

Successful responses reported 752 input tokens. At the configured input-only rate of
$0.10 per million tokens, their estimate is $0.0000752. This is not an invoice or the total
charged: timed-out requests, cache accounting and pricing adjustments are not included.
The default timeout and default-off Decisions flag remain unchanged. Follow-up testing
must explicitly budget calls and compare a longer timeout before changing the default.

Contract reference: [OpenAI Decisions API](https://developers.openai.com/api/reference/resources/decisions/methods/create).
Current acceptance status: [roadmap](../roadmap.md).
