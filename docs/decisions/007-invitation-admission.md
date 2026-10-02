# ADR 007: Invitations and conservative quota admission

Status: accepted 2026-09-30

Context: a public demonstration needs bounded spend and abuse resistance without introducing a full account system. A browser ownership key alone does not enforce per-person access policy.

Decision: authenticate named invitations, then require both the principal and session capability for session operations. Reserve daily sessions, voice seconds and active leases transactionally in local durable SQLite before provider setup. Hash principal names on disk. Reserve a full lifetime plus sweep margin, doubled for fallback, without refunding ambiguous usage. Use a startup-configured admission kill switch.

Consequences: stable invitation names preserve reservations through token rotation. Invitations identify bearer credentials, not verified people. SQLite suits one process or processes sharing one Docker host, not a cross-host replicated quota service. Quota storage failures reject new admission. Provider budget controls remain necessary after crashes and unconfirmed remote cleanup. Shared access codes remain restricted to private testing.

See [operations](../operations.md) and [production scope](../production.md).
