# Evals — M4

M1's runnable offline suite is in `backend/tests/`. This directory will hold sanitized recorded scenarios and pytest checks for delegation decisions, non-delegation cases, p50/p95 latency budgets, interruptions, and fallback completion time.

Fake-provider scenarios prove application behavior under scripted inputs. They do not establish real-model quality or real network latency. Keep live model checks and audio measurements separate and clearly labeled.
