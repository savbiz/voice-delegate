# API contracts

## Browser API

The backend serves JSON over HTTPS in hosted deployments. All `/api` routes require the exact configured `Origin`. Except `/api/config`, they also require `Authorization: Bearer <invitation>` when invitation/shared-code authentication is configured. Every session-specific route requires `X-Session-Key`; a different principal or key receives 404. The shared-code mode is for private testing only.

| Method | Route | Request / response | Success | Route-specific errors |
|---|---|---|---|---|
| GET | `/healthz` | `{"status":"ok"}`; process health, no provider call | 200 | — |
| POST | `/api/config` | `requires_access_code`, `voice_available`, `feedback_available` booleans | 200 | — |
| POST | `/api/sessions` | Optional `language` and `mode` preferences; returns `id`, `key`, `ttl_seconds` | 201 | 429 capacity/quota; 503 kill switch or quota store failure |
| POST | `/api/sessions/{id}/offer` | `{"sdp":"v=0\r\n…"}` → `{"sdp":"…"}` | 200 | 409 duplicate/invalid state; 502 provider failure; 504 setup timeout |
| POST | `/api/sessions/{id}/reconnect` | `sdp` and integer `generation` → SDP answer | 200 | 409 stale/used attempt or invalid state; 501 no replay-capable fallback; 502 provider failure; 504 timeout |
| POST | `/api/sessions/{id}/heartbeat` | No body → status payload described below | 200 | 404 expired/removed session |
| POST | `/api/sessions/{id}/interrupt` | No body → `delegation` status | 200 | — |
| POST | `/api/sessions/{id}/close` | No body → `{"finalized":true/false}` | 200 | 404 already removed |
| POST | `/api/sessions/{id}/token` | No supported browser credential contract | — | 501 unsupported |
| POST | `/api/reference/search` | `{"query":"…"}` (1–500 chars) → `sources`, `status` | 200 | — |
| POST | `/api/reference/{id}` | No body → source by corpus ID | 200 | 404 unknown source |
| POST | `/api/feedback` | `diagnostic_id` UUID, `category`, `state` → same diagnostic ID | 201 | 404 another principal's ID; 409 changed duplicate; 429 report quota; 503 disabled/full/unavailable store |

Common errors: 400 invalid Host; 401 authentication; 403 Origin; 404 missing session/ownership; 413 oversized request; 422 schema validation; 429 IP rate limit. Rate-limited responses carry `Cache-Control: no-store`. CORS preflight uses OPTIONS and checks the configured origin. Framework documentation routes (`/docs`, `/redoc`, `/openapi.json`, `/docs/oauth2-redirect`) are enabled outside production. In production, set `VOICE_API_DOCS=true` temporarily to expose Swagger; default off in production. ReDoc and the OpenAPI schema follow the same switch. Enabled documentation routes remain subject to host/body/rate middleware.

Preferences accept `language` = `auto`, `it`, `en`, `es`, `fr`, `de`; `mode` = `conversation` or `translate`. They are immutable during a session. SDP must start with `v=0`, contain a newline and be at most 64,000 characters. Reconnect generation must be nonnegative. Additional SDP/preference fields are rejected.

Heartbeat returns `state`, `delegation`, transport `generation`, `fallback_available`, `sources` and `recap`. State is one of `created`, `connecting`, `connected`, `reconnecting`, `closing`, `closed`; closed sessions are ordinarily removed and return 404. Delegation outcomes include idle/running/completed/cancelled/timeout/failed/busy/request_limit/delivery_failed. Recap has `latest_request`, `latest_reply`, `interrupted`, `revision`. Sources contain `id`, `title`, `path`, `section`, `text`, `digest`; heartbeat source text is clipped to 400 characters.

Feedback categories are `wrong_answer`, `source`, `audio`, `connection`, `other`; UI states are `ready`, `connecting`, `connected`, `working`, `busy`, `recovering`, `ended`. No free-text transcripts or credentials are accepted. Repeating the identical diagnostic ID/body is idempotent; a changed body conflicts.

## Private worker service

Run one worker service on a private network; every job request requires `Authorization: Bearer <VOICE_WORKER_SERVICE_TOKEN>` (at least 32 characters). Missing/incorrect tokens return 401. Do not expose the service directly to browsers.

| Method | Route | Contract | Success | Errors |
|---|---|---|---|---|
| POST | `/jobs` | `request_id` UUID, `goal` (1–8192 chars), optional `context` (≤32768 chars), finite Unix-seconds `deadline` | 202 with `status` | 401; 409 reused ID/different goal or context; 422 invalid/past/deadline over 120 seconds; 429 capacity/ledger full |
| GET | `/jobs/{key}` | Read UUID job; returns `status`, `text`, `source_ids` | 200 | 401; 404 missing/expired; 422 invalid UUID |
| DELETE | `/jobs/{key}` | Cancel UUID job or create cancellation tombstone | 200, `status=cancelled` | 401; 422 invalid UUID; 503 cancellation ledger full |

Body limits also return 413. The worker's framework documentation routes are enabled separately from job authentication; the service belongs on the private network regardless. `GET /jobs` is not a health endpoint; the bundled health probe POSTs `/jobs` without a token and expects 401.

Job states are `running`, `completed`, `cancelled`, `timeout`, `failed`. Results carry text and source IDs separately. The API polls every 200 ms and resolves IDs against its matching bundled corpus. Default capacity is 4 and the ledger holds 128 records. Jobs/tombstones are ephemeral with 180-second retention; active expired jobs are cancelled before removal. A repeated ID with the same fingerprint returns its existing state, including cancellation. Restart loses this ledger. No automatic execution retry is promised.

See [configuration](configuration.md), [operations](operations.md) and [architecture](architecture.md).
