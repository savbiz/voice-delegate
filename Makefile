# Run from the repository root. Application settings stay in .env or the environment.
.DEFAULT_GOAL := help
PROJECT_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
VITE_API_BASE_URL ?=

.PHONY: help be fe invite
help:
	@printf '%s\n' 'make be  Start local FastAPI at http://127.0.0.1:8000 (loads root .env).' 'make invite  Print the reusable invitation for make be.' 'make fe  Start Vite at http://127.0.0.1:5173 (uses local backend by default).' 'Options: VOICE_WORKER_MODE=openai make be' 'Remote API: make fe VITE_API_BASE_URL=https://your-api.example'

be:
	cd "$(PROJECT_ROOT)" && uv run python scripts/dev.py be

fe:
	cd "$(PROJECT_ROOT)/frontend" && VITE_API_BASE_URL="$(VITE_API_BASE_URL)" pnpm dev

invite:
	@cd "$(PROJECT_ROOT)" && uv run python scripts/dev.py invite
