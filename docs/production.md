# Production scope and remaining work

voice-delegate is a development reference for a controlled voice demo, not a hosted
multi-tenant service. The [architecture](architecture.md) describes its boundaries;
[deployment instructions](../deployment/README.md) describe the supported single-process
profile and private same-host scaling exercise. Live voice, Azure calls and public hosting
acceptance remain pending in the [roadmap](roadmap.md).

## What the reference implements

The backend owns session admission, capability keys, absolute and heartbeat deadlines,
bounded request bodies and queues, worker cancellation, and one explicit provider fallback.
Personal invitations gate the public demo. SQLite stores durable daily quota reservations
and bounded feedback, while transcripts and active session ownership remain in memory.
The demo also provides read-only documentation search and separate worker text/source results.

The frontend owns WebRTC media and releases it on teardown. Provider speech detection is
authoritative; the local detector is a latency optimisation. Optional OpenTelemetry exports
backend spans per turn and duration histograms. Deterministic tests verify orchestration;
paid text-worker evaluations are recorded separately from voice acceptance.

Deployment templates include non-root processes, health probes, runtime images without uv,
digest-pinned base images, bounded container resources and a hardened same-host gateway.
The API has an in-process per-IP limiter; Nginx also limits gateway requests. The same-host
example routes session IDs to their owning API and shares a SQLite volume. It does not
migrate live WebRTC connections after a process failure. See the recorded
[Docker verification](milestones/m7-m8-verification.md#docker-acceptance-exercise).

## What a multi-tenant deployment still needs

| Area | Required work beyond this reference |
|---|---|
| Session ownership | A shared ownership store with atomic leases, generation fencing, routing and failure recovery. A routing record cannot move an existing WebRTC peer; reconnect and user-visible loss must remain explicit. |
| Quotas and identity | A transactional quota store outside SQLite, tenant-aware authentication and authorization, distributed concurrency accounting, and auditable budget enforcement across regions and replicas. Invitation tokens are a demo gate, not a full identity system. |
| Edge protection | An edge WAF and coordinated rate limits, abuse detection, request-size limits and restrictions preventing direct backend access. Per-process buckets do not provide a fleet-wide quota. |
| Service transport | TLS between services, authenticated workload identities or managed secret rotation, and network policies. Plain HTTP in the Compose example is confined to a private same-host network. |
| Backups and restore | Encrypted backups of durable quota and feedback data, retention/deletion policies, tested restores and agreed recovery objectives. Persistent volumes alone are not backups. |
| Alerts and SLOs | Defined availability, setup, interruption and latency SLOs; alert thresholds, ownership, escalation and runbooks. Establish these from real provider and device measurements, not simulated timings. |
| Trace storage | An authenticated collector path and a durable trace backend with sampling, retention and tenant/privacy controls. The local collector logs traces and has no trace storage service. |
| Image provenance | Signed artifacts, verified build provenance, SBOMs, vulnerability scanning and a process to rebuild and promote patched images. Digest pins identify content; they do not establish who built it or that it is secure. |

Provider project keys and provider-side spending limits remain necessary alongside
application quotas. Cleanup can be unconfirmed and provider activity can outlive a local
process. Operators also need secrets rotation, incident response and deployment rollback
procedures appropriate to their environment.

## Deliberate limits of the reference

Shared ownership, distributed quotas and tenant identity are deliberately out of scope:
they require a selected database, consistency model and tenant policy. The same-host
example demonstrates the process boundary without claiming distributed high availability.

An edge WAF, inter-service TLS infrastructure, managed backups, paging, SLO commitments,
trace storage and signed image promotion are also deliberately out of scope. Their
implementation depends on the hosting platform, trust boundary, retention requirements
and operating team. Adding placeholder infrastructure would not establish those guarantees.
The table above is work an operator must complete before making multi-tenant production claims.

Real microphone, browser/device acoustics and Azure recovery acceptance are pending
verification rather than deliberately omitted requirements. Record actual model names,
region, device, network, executed steps and measurements in the
[live verification template](milestones/live-verification.md); leave unmeasured fields empty.
