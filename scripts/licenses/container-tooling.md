## Optional container and development tooling

These tools are fetched from upstream registries for the optional offline stack;
they are not added to the Python or browser dependency graph. Container images also
contain operating-system packages with their own licences. Retain the upstream image
licence material when redistributing images; this table is not an OS package inventory.

| Tool / configured version | Licence | Upstream licence and attribution |
|---|---|---|
| Node.js 24, Debian bookworm slim build image | MIT, with bundled third-party terms | [Node.js licence and copyrights](https://github.com/nodejs/node/blob/v24.x/LICENSE) |
| nginx 1.27.4 Alpine frontend image | BSD-2-Clause, plus image packages | [nginx copyright and licence](https://nginx.org/LICENSE) |
| Dev Containers base Ubuntu 24.04 | MIT for image configuration, plus Ubuntu packages | [devcontainers/images licence](https://github.com/devcontainers/images/blob/main/LICENSE) |
| Dev Containers docker-in-docker feature 2 | MIT for feature scripts; Docker/Moby Apache-2.0 | [feature licence](https://github.com/devcontainers/features/blob/main/LICENSE), [Moby licence](https://github.com/moby/moby/blob/master/LICENSE) |
| OpenTelemetry Collector Contrib 0.123.0 | Apache-2.0 | [Collector licence](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.123.0/LICENSE) |
| Prometheus 3.2.1 | Apache-2.0 | [Prometheus licence](https://github.com/prometheus/prometheus/blob/v3.2.1/LICENSE), [NOTICE](https://github.com/prometheus/prometheus/blob/v3.2.1/NOTICE) |
| Grafana 11.6.0 | AGPL-3.0-only | [Grafana licence](https://github.com/grafana/grafana/blob/v11.6.0/LICENSE) |

uv 0.12.15 and pnpm 11.19.0 are existing build tools; their installed dependency
attributions are included above where present. This optional stack does not grant
clearance for internal organisational use; review the exact images you distribute.
