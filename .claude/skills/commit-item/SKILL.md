---
name: commit-item
description: Create the commit for one numbered work item following this repository's rules - staged-file review, forbidden file patterns, checks, attribution and no push. Use whenever asked to commit or when finishing a numbered item.
---

# Commit one item

One commit per numbered item. Never push; the author pushes manually. Never create or
switch a repository to public.

## Steps

1. Stage only files that belong to this item (`git add <paths>`, not `git add -A`).
2. List what is staged: `git diff --cached --name-status`.
3. Refuse and unstage if any staged path matches `.env*` (except `.env.example`), `*.pem`,
   `*.key`, or a name containing `secret` or `credential`. Never commit provider keys,
   invitations, session keys or recordings. Use synthetic fixtures.
4. Run the `independence-check` skill, then the `repo-checks` skill. Resolve failures
   before committing.
5. If a dependency was added, confirm `THIRD_PARTY_NOTICES.md` was updated
   (`add-dependency` skill).
6. Commit with an imperative, specific subject and a short body explaining why. Add the
   attribution trailer the current session instructs. Then run `git status` to confirm a
   clean tree for the item.
7. Run all checks again after the commit and fix anything that fails before the next item.

## Never

- `git push`, `gh repo create` without `--private`, or any visibility change.
- `--no-verify` or amending/rewriting commits the author already pushed.
- Mentioning the author's employer, its products, people, events or documents anywhere in
  the message or diff.
