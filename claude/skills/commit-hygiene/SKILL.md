---
name: commit-hygiene
description: The one way to commit in a client worktree, and what it refuses.
---

# Commit hygiene

One command commits, from any directory:
```
$HARNESS_WORKSPACE/harness/bin/commit <slug> <repo> "<subject>" [--body "<text>"]
```
It stages every change in `.worktrees/<slug>/<repo>` and refuses the whole commit when any path or the message breaks a rule. Nothing is dropped silently. Fix the cause, rerun.

Refused paths: `state.json`, `plan.md`, `retro.md`, `spec-gaps.md`, `journey.md`, `decisions.md`, `CLAUDE.md`, `*.harness.*`, `.env`, `*.env`, anything under `.claude/`, `product/`, `harness/`, `secrets/` or `.worktrees/`, any link pointing outside the worktree. Delete or move the file, rerun.

Message: one line, imperative, under 72 characters, what the code now does, in feature vocabulary. Example: `Add coupon validation to checkout form`. Optional body after a blank line. Refused: sub-task ids, ticket ids, feature slugs, the words harness, agent, Claude and AI, internal file names, dates.

Identity comes from `delivery.commit_author`. Never run `git commit` yourself. Never set an author or a trailer. Never read the client's history for style.

Push only at delivery, only the feature branch, from the worktree: `git push origin <branch>`. The hook refuses every other ref, every force and every deletion. A refused push is a friction to record, never a retry with other arguments.
