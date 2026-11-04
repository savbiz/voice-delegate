# Nightly results

A workflow measures the offline stack every night and builds a small static page from the numbers,
so the figures quoted about this project cannot go stale. Nothing in it calls a voice provider or
costs money.

## What is measured

| Measure | How | Source |
|---|---|---|
| Tests and line coverage | the full `pytest` suite with coverage | `uv run pytest` |
| Load | 40 concurrent virtual users for 30 seconds against an isolated offline backend; per-endpoint p50, p95 and p99, failures and shed requests | [load testing](load-testing.md) |
| Worker evaluation | the 40-case worker dataset with the scripted offline planner | [evals](../evals/README.md) |

The evaluation is a **control check** of the retrieval, tool and citation plumbing. The planner is
scripted, so a perfect score says nothing about model quality, and the page says so.

## Where it appears

Every run, with no setup: the numbers are in the run's **job summary** (Actions, the `results`
workflow) and attached as the `site` artifact (`index.html` and `results.json`).

As a public page, after one-time setup by the repository owner:

1. Settings, Pages, Source: **GitHub Actions**.
2. Settings, Secrets and variables, Actions, Variables: add `PUBLISH_RESULTS` with the value `true`.

The next nightly run then deploys the page to `https://<owner>.github.io/voice-delegate/`. Until
both steps are done the `publish` job is skipped and nothing is exposed.

The page keeps its own history without writing to the repository: each night the workflow downloads
the `results.json` it published the night before, appends the new run (keeping the newest 90) and
publishes the extended file. If that download fails, the history simply restarts.

## Reading it

The runner is a shared GitHub-hosted machine, so absolute latencies move from night to night. Read
the trend, not one value. The workflow publishes even when a check fails, so a regression is visible
on the page, and the run itself fails.

Run the pieces by hand: `scripts/build_results.py` takes the junit, coverage, load-test and
evaluation files and writes `results.json`, `index.html` and `summary.md`.
