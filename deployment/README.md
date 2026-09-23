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
| `VOICE_ACCESS_TOKEN` | Random shared demo access code, at least 24 characters; secret |
| `VOICE_ALLOWED_ORIGIN` | Exact production frontend URL, e.g. `https://voice-delegate.vercel.app`; no trailing slash |
| `VOICE_ALLOWED_HOSTS` | JSON array containing the backend public hostname, e.g. `["your-service.onrender.com"]` |
| `VOICE_MAX_SESSIONS` | `4` initially |
| `VOICE_SESSION_TTL_SECONDS` | `300` initially |

For Railway, include its healthcheck hostname too: `VOICE_ALLOWED_HOSTS=["your-service.up.railway.app","healthcheck.railway.app"]`. This is required by [Railway healthchecks](https://docs.railway.com/deployments/healthchecks). The setup uses the documented [Dockerfile service variable](https://docs.railway.com/builds/dockerfiles); legacy railway.toml config is deprecated for new services.

Generate the access code locally with `uv run python -c 'import secrets; print(secrets.token_urlsafe(32))'`. Share it only with demo users, who enter it in the frontend field. Keep it out of Git and build logs. Check `/healthz`, set Vercel's backend URL, redeploy the frontend, and test using the exact permitted origin. Preview deployment URLs are not automatically allowed.

The shared code gates a controlled demo, not a multiuser production service. Before general public access, add individual authentication, per-user quotas and rate limiting. Origin checks alone do not authenticate callers. Concurrent session and lifetime limits bound individual usage, not total monthly spend. Configure billing budgets separately.

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
