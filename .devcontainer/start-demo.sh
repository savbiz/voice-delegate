#!/usr/bin/env bash
set -euo pipefail
if [ -n "${CODESPACE_NAME:-}" ]; then
  export DEMO_ORIGIN="https://${CODESPACE_NAME}-8080.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}"
fi
docker compose -f deployment/demo/compose.yaml up --build -d --wait
