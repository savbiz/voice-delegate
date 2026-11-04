# ADR 010: Worker as a read-only MCP client

Date: 2026-11-04
Status: accepted

## Context

MCP offers tool discovery and invocation, but a server is not trusted by speaking it, and
tool annotations such as `readOnlyHint` are hints from the server, not guarantees. The voice
model keeps one tool, `delegate_task`; any new capability belongs to the worker. Moderation
([ADR 013](013-moderation-boundary.md)) must stand between external output and the planner
before remote tools are allowed.

## Decision

The worker can call tools on servers listed in `VOICE_MCP_SERVERS`. An entry names a server
id, a fixed HTTPS endpoint (no credentials, query, fragment or custom port), the exact tools
the operator has audited, and optionally the name of one `MCP_*` environment variable that
holds a bearer token. Servers are never discovered from speech, search results or tool
output, and no invitation code or provider key is forwarded. Any server requires
`VOICE_MODERATION`, so every MCP result is reviewed with the MCP origin first.

The client is a small JSON-RPC adapter over the existing `httpx` dependency (Streamable HTTP;
JSON or a single event-stream reply; no redirects, retries or SDK; protocol versions
2025-06-18 and 2025-03-26 only). Each operation uses a fresh short-lived protocol session.

- Discovery runs at most once per cache lifetime per server (default 60 s; a failed server is
  retried after 10 s), with 3 pages, 64 raw tools, a per-request timeout of at most 3 s and a
  5 s discovery cap. A refresh builds a new immutable snapshot; each delegation keeps the
  snapshot it started with. Discovery never happens per planner step.
- A tool is kept only if the operator listed it, its name is unique in the response, it does
  not declare `readOnlyHint: false`, and its parameter schema is a flat object of at most eight
  string, integer, number or boolean properties. Anything else (nested objects, arrays,
  references, unions) is dropped rather than approximated. Arguments are validated against
  the derived model before a request leaves the process.
- Names are prefixed `server__tool`. The total across servers is at most eight, so the
  Decisions choice list keeps room for built-ins, direct answers and refusals. The Decisions
  planner can call only a tool whose single required parameter is text, passing the goal
  verbatim; a model planner may supply validated arguments for others.
- A call has a bounded deadline, at most 8 KiB of text, and only `text` content; other
  content types are unavailable. Tool-reported errors (`isError`) are kept separate from
  transport failures. An invocation is never retried, and cancellation propagates.
- Output is moderated, then becomes one cited source (400-character excerpt). As with web
  evidence, no tool call may follow it, and at most three citations survive. A failure ends
  with an explicit unavailable result; built-in tools stay available when a server is down.
- Sessions that bring their own keys never receive operator servers. A private worker applies
  the same policy and validates returned MCP sources before the API accepts them.

## Consequences

Disabled mode is unchanged and adds no dependency. Fakes prove that the application
enforces the allowlist, schema review, bounds and quarantine; they do not prove a remote
server is honest or that a listed tool is truly read-only. The operator audits each listed
tool and should give the server read-only credentials and egress limits. Live
compatibility needs a separately authorized server and its recorded version. The proposed
ICS calendar example server is not part of this change.

## Public sources

- [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
- [MCP transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)
