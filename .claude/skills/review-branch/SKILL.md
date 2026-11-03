---
name: review-branch
description: Review a feature branch or git worktree under .local/worktrees against origin/main, including stacked or merged branches. Use when asked whether an implementation makes sense, to review a branch, or to rebase one onto main.
---

# Review a branch

Branches often live in worktrees under `.local/worktrees/`. Work from the worktree
directory and never alter another worktree or the shared stash (no bare `git stash`).

## Establish scope first

```sh
git fetch
git worktree list
git merge-base origin/main <branch>
git log --oneline --graph origin/main..<branch>
git diff --stat origin/main...<branch>
```

- Local `main` can lag `origin/main`; compare against `origin/main`.
- A branch stacked on other work shows an inflated diff. Identify the commits that are
  unique, and read docs in the branch (`docs/`) for stated intent.
- Check whether the branch is already pushed (`git rev-parse --abbrev-ref @{u}`).

## Review focus

- Contracts: public HTTP, provider and webhook behaviour must be preserved or migrated.
- Security: secrets lifetime, authorization on every new route, SSRF and origin checks,
  rate limiting, capacity and admission accounting, cleanup on every error path.
- Frontend/backend agreement: every state used after a reset (for example flags cleared
  after submit) must still reach recovery and reconnect paths.
- Tests: new behaviour has offline tests, including failure and recovery paths.
- Run the `repo-checks` skill and report results honestly.

## Rebasing a stacked branch onto main

- Make a backup branch first. Prefer `git rebase --onto origin/main <old-base> <branch>`.
- If squashed upstream commits make the replay conflict, abort. Instead build a single
  commit whose tree equals the old merge tree on top of `origin/main`, then cherry-pick
  the remaining unique commits. Verify `git diff <backup> HEAD` is empty.
- Never push or force-push; tell the author the branch needs a force push.

## Report

Give a verdict first, then concrete findings ordered by severity with file references.
Say what you verified by running and what you only read.
