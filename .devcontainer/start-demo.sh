#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

compose=(docker compose -f deployment/demo/compose.yaml)
diagnostics() {
  echo 'Inspect the stack: docker compose -f deployment/demo/compose.yaml ps'
  echo 'Inspect recent logs: docker compose -f deployment/demo/compose.yaml logs --tail 30'
}

# Docker-in-Docker can start after the container lifecycle hook.
ready=false
deadline=$((SECONDS + 120))
probe=
trap 'if [ -n "$probe" ]; then kill "$probe" 2>/dev/null || true; fi' EXIT
for ((attempt=0; attempt<120; attempt++)); do
  # Bound even a docker info process that stalls while the daemon is booting.
  docker info >/dev/null 2>&1 &
  probe=$!
  while kill -0 "$probe" 2>/dev/null; do
    if ((SECONDS >= deadline)); then
      kill "$probe" 2>/dev/null || true
      wait "$probe" 2>/dev/null || true
      probe=
      break 2
    fi
    sleep 1
  done
  if wait "$probe"; then
    probe=
    ready=true
    break
  fi
  probe=
  if ((SECONDS >= deadline)); then break; fi
  sleep 1
done
if [ "$ready" != true ]; then
  echo 'Docker did not become ready within 120 seconds.' >&2
  diagnostics
  exit 1
fi

origin=http://localhost:8080
origins='["http://localhost:8080"]'
if [ -n "${CODESPACE_NAME:-}" ]; then
  origin="https://${CODESPACE_NAME}-8080.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
  # Only platform-provided DNS labels belong in the persisted JSON/dotenv value.
  if [[ ! "$origin" =~ ^https://[a-zA-Z0-9.-]+$ ]]; then
    echo 'Invalid Codespaces forwarding hostname.' >&2
    exit 1
  fi
  origins="[\"http://localhost:8080\",\"https://localhost:8080\",\"${origin}\"]"
fi
umask 077
printf "DEMO_ALLOWED_ORIGINS='%s'\n" "$origins" > deployment/demo/.env
# Explicit environment also prevents a root .env from replacing the derived list.
export DEMO_ALLOWED_ORIGINS="$origins"
if ! "${compose[@]}" up --build -d --wait; then
  "${compose[@]}" logs --tail 30 >&2 || true
  diagnostics
  exit 1
fi
printf 'Offline demo: %s (keep forwarded ports private)\n' "$origin"
diagnostics
