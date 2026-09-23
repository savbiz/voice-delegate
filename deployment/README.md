# GitHub and deployment

Deploy the frontend to Vercel and **one** persistent backend process to Railway or Render. WebRTC media connects the browser to the provider; Python keeps the control WebSocket. Vercel serves the static frontend, not the Python session manager. The in-memory registry requires one replica and one Uvicorn worker. Restarting or redeploying interrupts active sessions.

## 1. Publish on GitHub

The supplied archive includes a Git checkout with conventional commits. Open the extracted `voice-delegate/` directory and check `git status`. With the GitHub CLI installed:

```bash
gh auth login
gh repo create voice-delegate --public --source=. --remote=origin --push
```

Alternatively create an **empty** repository on GitHub without initializing README/license, then run:

```bash
git remote add origin https://github.com/YOUR_USERNAME/voice-delegate.git
git push -u origin main
```

Replace YOUR_USERNAME. No GitHub repository is created automatically by this archive. GitHub Actions runs Python checks, frontend build, Vitest and Chromium Playwright on pushes and pull requests; no API secrets are required. Apache-2.0 and NOTICE are included. Rename the placeholder project before publication if desired.

## 2. Frontend on Vercel

Import the GitHub repository. Set **Root Directory = frontend**, framework Vite, install `pnpm install --frozen-lockfile`, build `pnpm build`, output `dist`, Node.js 24. `frontend/vercel.json` supplies build defaults. The simulated demo works immediately without a backend or API key.

Once the backend URL exists, set the **public** build variable `VITE_API_BASE_URL=https://YOUR_BACKEND_HOST` (no trailing slash), then redeploy. Never place OPENAI_API_KEY or VOICE_ACCESS_TOKEN in a VITE variable: Vite embeds them in public JavaScript.

## 3. Backend on Render OR Railway

Both platforms build `deployment/Dockerfile.backend` with the **repository root** as Docker context. `/healthz` is the health endpoint. The container reads PORT and runs as a non-root user.

- **Render:** New Blueprint, connect the GitHub repo, use root `render.yaml`. Choose a service plan and review its cost before deploying. Fill the environment values requested by the blueprint.
- **Railway:** New Project → deploy from GitHub, select the repo, leave the root directory at the repository root. Set service variable `RAILWAY_DOCKERFILE_PATH=deployment/Dockerfile.backend`, healthcheck path `/healthz` in Settings, and one replica. Generate a public domain. Add the variables below before expecting a healthy production startup.

Use these environment settings in the backend service dashboard:

| Variable | Value |
|---|---|
| `VOICE_ENVIRONMENT` | `production` |
| `OPENAI_API_KEY` | Your provider project key; secret |
| `VOICE_PUBLIC_DEMO` | `true` |
| `VOICE_INVITE_TOKENS` | Secret JSON mapping invitation names to unique random tokens of at least 32 characters |
| `VOICE_QUOTA_DATABASE` | `/app/.local/quotas.sqlite3` on persistent storage |
| `VOICE_FEEDBACK_DATABASE` | `/app/.local/feedback.sqlite3` on persistent storage |
| `VOICE_ALLOWED_ORIGIN` | Exact production frontend URL, e.g. `https://voice-delegate.vercel.app`; no trailing slash |
| `VOICE_ALLOWED_HOSTS` | JSON array containing the backend public hostname, e.g. `["your-service.onrender.com"]` |
| `VOICE_MAX_SESSIONS` | `4` initially |
| `VOICE_SESSION_TTL_SECONDS` | `300` initially |

For Railway, include its healthcheck hostname too: `VOICE_ALLOWED_HOSTS=["your-service.up.railway.app","healthcheck.railway.app"]`. This is required by [Railway healthchecks](https://docs.railway.com/deployments/healthchecks). The setup uses the documented [Dockerfile service variable](https://docs.railway.com/builds/dockerfiles); legacy railway.toml config is deprecated for new services.

Generate each invitation token locally with `uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Assign each token a distinct invitation name and share it only with that user, who enter it in the frontend field. Keep it out of Git and build logs. Check `/healthz`, set Vercel's backend URL, redeploy the frontend, and test using the exact permitted origin. Preview deployment URLs are not automatically allowed.

The single shared `VOICE_ACCESS_TOKEN` mode is for private testing only. Public demos require named invitations and durable quotas. Origin checks alone do not authenticate callers. The Render blueprint provisions a 1 GB disk at `/app/.local`; Railway needs an equivalent persistent volume.

Hosting plans, sleep policies and quotas change: check the platform dashboards before accepting costs. A sleeping backend adds cold-start latency and cannot sustain active control sessions while asleep. The free frontend simulation needs no paid model; live provider calls are billed separately from hosting.

## M2 worker settings

The Dockerfile includes both uv workspace packages (`backend/` and `agent/`). Keep the build context at the repository root. For natural-language work, add `VOICE_WORKER_MODE=openai` and `VOICE_WORKER_MODEL=gpt-4.1-mini` to backend service variables, with the existing project API key. This adds text-model usage charges. Leaving worker mode at its default `offline` uses a scripted planner. Worker configuration never belongs in Vercel's public build variables. See [M2](../docs/milestones/m2.md).

## Local container check

With Docker installed, from the repository root:

```bash
docker build -f deployment/Dockerfile.backend -t voice-delegate-api .
docker run --rm --env-file .env -p 8000:8000 voice-delegate-api
```

This container uses your local development origin unless production settings are supplied. `.env` is excluded from the image. Docker and hosted deployment must be validated in your environment; the delivered candidate is checked through local Python and browser tools.

Public references: [Vercel Vite](https://vercel.com/docs/frameworks/frontend/vite), [Render FastAPI](https://render.com/docs/deploy-fastapi), [Railway FastAPI](https://docs.railway.com/guides/fastapi).

## M5 controlled public demo

Use [M5 configuration and rollback](../docs/milestones/m5.md) before opening access to other users.
Personal invitation tokens replace a shared code in public-demo mode. Mount durable quota
storage at `/app/.local` owned by UID 10001, and keep one API worker. Reuse that volume across
image replacement and rollback. Admission reserves the full session allowance up front;
there are no refunds on failed creation. Local Docker checks cover authentication and
quota persistence after restart, not the availability of a publicly hosted deployment.

The [M6 documentation workflow](../docs/milestones/m6.md) is bundled with the agent and available
through the Documentation tab without a paid model call.


## Cost controls

Use separate project-scoped OpenAI service-account keys for this demo and development;
use a dedicated Azure OpenAI resource and resource-scoped key for the demo. Keep both on
the backend, rotate them, and restrict permitted models/deployments and access.

Set hard monthly budgets for both providers before inviting users:

- **OpenAI:** configure the project monthly spend limit and enable **Enforce a hard limit**;
  also set alerts below that threshold. Enforcement can lag tracked spend, so leave headroom.
  See [OpenAI spend limits](https://developers.openai.com/api/docs/guides/spend-limits).
- **Azure:** set a monthly Cost Management budget for the dedicated resource and connect
  budget alerts to a tested shutdown procedure that disables demo admission and stops
  billable provider access. Azure budgets alone do **not** stop consumption; alert data and
  automation can lag. An exact hard monthly cap cannot be promised by this configuration.
  If a strict ceiling is required, keep the public demo disabled until an enforced spending
  control is available and verified for the subscription. See
  [Azure budgets](https://learn.microsoft.com/en-us/azure/cost-management-billing/costs/tutorial-acm-create-budgets).

These application limits supplement provider spending controls; seconds are reserved
allowances, not currency or measured billing. Daily counters reset at UTC midnight.

| Setting | Default | Meaning |
|---|---|---|
| `VOICE_PUBLIC_DEMO` | `false` (blueprint: `true`) | Requires production configuration, named invites and durable quota storage. |
| `VOICE_INVITE_TOKENS` | `{}` | Up to 100 named, unique invitation tokens; identity for personal quotas. |
| `VOICE_QUOTA_DATABASE` | `.local/quotas.sqlite3` | Durable daily reservations and active-session leases; retain across restarts. |
| `VOICE_DEMO_ENABLED` | `true` | Admission kill switch; `false` rejects new sessions, without ending existing calls. |
| `VOICE_DAILY_SESSIONS_PER_USER` | `4` | Maximum session reservations per invitation per UTC day. |
| `VOICE_CONCURRENT_SESSIONS_PER_USER` | `1` | Maximum simultaneously active sessions per invitation. |
| `VOICE_DAILY_VOICE_SECONDS_PER_USER` | `1500` | Per-invitation daily reserved provider seconds. |
| `VOICE_DAILY_VOICE_SECONDS_GLOBAL` | `6000` | Daily reserved provider seconds across all invitations. |
| `VOICE_MAX_SESSIONS` | `4` | Total active session capacity; public-demo leases share the limit through the database. |
| `VOICE_SESSION_TTL_SECONDS` | `300` | Absolute session lifetime; heartbeats never extend it. |
| `VOICE_HEARTBEAT_TIMEOUT_SECONDS` | `45` | Expire sessions whose browser stops sending heartbeats. |
| `VOICE_MAX_DELEGATIONS_PER_SESSION` | `8` | Unique worker requests allowed per session; repeats do not create new work. |
| `VOICE_DELEGATION_TIMEOUT_SECONDS` | `15` | Deadline for each worker task. |
| `VOICE_WORKER_MAX_STEPS` | `4` | Maximum model reasoning steps per worker invocation. |
| `VOICE_DELEGATION_RESULT_TOKENS` | `120` | Spoken result token budget, additionally capped at 500 UTF-8 bytes. |
| `VOICE_WORKER_SERVICE_CAPACITY` | `4` | Concurrent tasks in the optional remote worker; excess work is rejected. |
| `VOICE_WORKER_MAX_RECORDS` | `128` | Maximum remote job/cancellation records retained at once. |

Each admission reserves `ceil(VOICE_SESSION_TTL_SECONDS + 1)` seconds, doubled when
`VOICE_FALLBACK_ENABLED=true` to cover both providers. Failed setup, early close and
interruption do not refund daily reservations. Active leases are released on close or
expire after the lifetime plus setup/close allowances. Text-worker token charges and
hosting/storage charges are separate from the voice-second allowance.

The API also limits each client IP to 20 HTTP requests/second with a burst of 100,
before reading request bodies. Buckets are per process, capped at 10,000 active clients;
new clients receive 429 while that table is full. Idle buckets expire after five seconds.
Keep `VOICE_TRUST_PROXY=false` for direct access. Set it to `true` only behind an ingress
that overwrites `X-Forwarded-For` with a trustworthy client address and prevents direct
access to the backend; the first address is used. Run Uvicorn with `--no-proxy-headers`
(as the container does), so this setting exclusively controls forwarded-header trust.
Invalid forwarded addresses fall back to the socket peer. Multi-process/global limits
require an external shared limiter.
