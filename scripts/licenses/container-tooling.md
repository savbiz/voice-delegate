## Optional container and development tooling

These tools are fetched from upstream registries for the optional offline stack;
they are not added to the Python or browser dependency graph. Container images also
contain operating-system packages with their own licences. Retain the upstream image
licence material when redistributing images; this table is not an OS package inventory.

| Tool / configured version | Licence | Upstream licence and attribution |
|---|---|---|
| Node.js 24, Debian bookworm slim build image | MIT, with bundled third-party terms | [Node.js licence and copyrights](https://github.com/nodejs/node/blob/v24.x/LICENSE) |
| nginx 1.30.6 Alpine frontend image | BSD-2-Clause, plus image packages | [nginx copyright and licence](https://nginx.org/LICENSE) |
| Dev Containers base Ubuntu 24.04 | MIT for image configuration, plus Ubuntu packages | [devcontainers/images licence](https://github.com/devcontainers/images/blob/main/LICENSE) |
| Dev Containers docker-in-docker feature 2 | MIT for feature scripts; Docker/Moby Apache-2.0 | [feature licence](https://github.com/devcontainers/features/blob/main/LICENSE), [Moby licence](https://github.com/moby/moby/blob/master/LICENSE) |
| OpenTelemetry Collector Contrib 0.123.0 | Apache-2.0 | [Collector licence](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/v0.123.0/LICENSE) |
| Prometheus 3.2.1 | Apache-2.0 | [Prometheus licence](https://github.com/prometheus/prometheus/blob/v3.2.1/LICENSE), [NOTICE](https://github.com/prometheus/prometheus/blob/v3.2.1/NOTICE) |
| Grafana 11.6.0 | AGPL-3.0-only | [Grafana licence](https://github.com/grafana/grafana/blob/v11.6.0/LICENSE) |
| Railway TypeScript SDK `railway` 3.16.0, with `graphql` 16.14.2 and `@graphql-typed-document-node/core` 3.2.0 (`.railway/` only, for `railway config plan`) | MIT | [railway-ts-sdk](https://github.com/railwayapp/railway-ts-sdk), [graphql-js licence](https://github.com/graphql/graphql-js/blob/v16.14.2/LICENSE), [typed-document-node licence](https://github.com/dotansimha/graphql-typed-document-node/blob/master/LICENSE) |
| pip-audit 2.10.1 (CI only, run with `uv tool run`) | Apache-2.0 | [pip-audit licence](https://github.com/pypa/pip-audit/blob/v2.10.1/LICENSE) |
| OpenSSF Scorecard action 2.5.0 (CI only) | Apache-2.0 | [scorecard-action licence](https://github.com/ossf/scorecard-action/blob/v2.5.0/LICENSE) |
| `actions/upload-artifact` 7.0.2 (CI only) | MIT | [licence](https://github.com/actions/upload-artifact/blob/v7.0.2/LICENSE) |
| Trivy 0.76.1, run by `aquasecurity/trivy-action` 0.36.0 (CI only, scans the built images) | Apache-2.0 | [Trivy licence](https://github.com/aquasecurity/trivy/blob/v0.76.1/LICENSE), [trivy-action licence](https://github.com/aquasecurity/trivy-action/blob/v0.36.0/LICENSE) |
| pre-commit 4.7.0 (optional developer tool, installed by the developer with `uv tool install`; the repository fetches no hook repository) | MIT | [pre-commit licence](https://github.com/pre-commit/pre-commit/blob/v4.7.0/LICENSE) |
| `actions/upload-pages-artifact` 5.0.0 and `actions/deploy-pages` 5.0.1 (CI only, publish the nightly results page) | MIT | [upload-pages-artifact licence](https://github.com/actions/upload-pages-artifact/blob/v5.0.0/LICENSE), [deploy-pages licence](https://github.com/actions/deploy-pages/blob/v5.0.1/LICENSE) |

uv 0.12.15 and pnpm 11.19.0 are existing build tools; their installed dependency
attributions are included above where present. This optional stack does not grant
clearance for internal organisational use; review the exact images you distribute.
