FROM ghcr.io/astral-sh/uv:0.12.15@sha256:62f8c047d0a0e9ece6b53fc63df902585a67a47a7f318ddec4a37db586edc8e3 AS uv
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04
COPY --from=uv /uv /uvx /usr/local/bin/
