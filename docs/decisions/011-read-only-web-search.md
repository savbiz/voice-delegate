# ADR 011: Read-only web search in the delegated worker

Date: 2026-11-01
Status: accepted

## Context

The voice model retains its single `delegate_task` entry point. The worker needs a
bounded source of current public information alongside calculation and bundled
project documentation. External search results are untrusted evidence. The default
offline demo must continue to work without credentials or network requests.

## Decision

Use Tavily Basic Search through a small HTTP adapter, without a search SDK. It
returns structured URLs, titles and excerpts and supports an optional domain filter.
Disable generated answers, raw page content, images and automatic search-depth
selection. Use the existing `httpx` dependency, now explicitly declared by the agent
package; its BSD-3-Clause attribution is already in THIRD_PARTY_NOTICES.md.

Brave offers structured web results and Exa offers search with selectable content.
Tavily is the initial integration choice for the bounded excerpt contract and direct
domain filtering. No comparative live quality, latency or cost benchmark establishes
it as the best provider. The adapter is separate from the planner and voice provider.

One request has a configurable total deadline, at most five seconds, a 64 KiB
response limit, three results and no retries, redirects or local fetching of result
URLs. URLs must be public-form HTTPS DNS names without credentials or custom ports;
links are not proof of a site's trustworthiness. Optional allowlisting matches exact
domains and their subdomains. Excerpts are clipped to the existing 400-character
source budget, titles to 160 characters and URLs to 2048 characters.

`VOICE_WEB_SEARCH` defaults to false. Enabling it requires `TAVILY_API_KEY` on the
worker host. Transport, status, deadline and malformed-response failures explicitly
fall back to bundled project documentation, with a disclosure in the worker result.
No results means no supported web answer. Task cancellation propagates rather than
being turned into a fallback answer.

After web evidence is read, the graph allows only a final answer: further tool calls
are rejected in code. Calculation or project search can precede web search within
the existing step budget. This limits the first implementation's multi-step workflows
and prevents search-result instructions from launching another tool. Final web
answers need valid source indices; citations do not prove semantic accuracy. This is
not a replacement for the planned moderation extension or a guarantee that an LLM
will never repeat malicious text.

## Consequences

Both local and private workers use the same configured tool registry. Private job
results carry up to three validated web sources so cited evidence reaches the UI.
The browser receives sources through the existing authenticated API; it never
receives the search key. Voice providers continue to see only `delegate_task`.

Queries are sent to Tavily and selected excerpts enter the configured worker and
voice provider flows. No full conversation is sent by the search adapter, but a
model-generated query can contain user-supplied details. Operators should enable
search only when that data flow and their provider plan are acceptable. Free
credits are an account allowance, not an application spending guarantee.

Offline HTTP fakes verify routing, budgets, failures, citations and blocked follow-up
tool execution. Live relevance, answer grounding, paid account behavior and narration
remain pending. The existing offline demo keeps search disabled.

## Public sources

- [Tavily Search API](https://docs.tavily.com/documentation/api-reference/endpoint/search)
- [Tavily credits and pricing](https://docs.tavily.com/documentation/api-credits)
- [Brave Search API](https://api-dashboard.search.brave.com/api-reference/web/search/get)
- [Exa Search API](https://exa.ai/docs/reference/search)
