---
name: retro
description: The retrospective as a checklist, from frictions to a pushed and tagged engine.
---

# Retro

Engine edits go under `harness/`. Product writes: `retro.md` and `conventions.md` only.

1. Read `state.json`: frictions, blocked items, attempts and interruptions, cost per sub-task, budget overrun, accepted gaps, reactions from Ali.
2. Compare this run's totals with the median of the previous three runs in this workspace's `cost-log.md`: tokens, wall time, blocked count, attempts per sub-task. Fewer than three runs: one line saying there is no baseline. Any total more than 50% worse with no matching growth in feature size: write it at the top of `retro.md` as a suspected regression, name the harness commits between `harness_commit` and HEAD, add an entry to `OPEN_QUESTIONS.md`. Decide nothing about the cause.
3. `git -C harness pull`. Read `git log <harness_commit>..HEAD` with diffs.
4. Drop every friction a commit in that range already addresses.
5. Generalise each remaining friction: strip client, repo, service, domain, person, endpoint, table and branch names. A friction that cannot be stated without them goes to `product/conventions.md`, not the engine.
6. Write each fix into the harness file that owns the subject by rewriting the existing rule in place. Add a rule only for a subject no file covers. Stay under every file's cap; consolidate at the cap. A file that grew across three consecutive retros while none shrank: entry in `OPEN_QUESTIONS.md`, no edit.
7. Rewrite `harness/STATE.md` when the engine changed: what it is now, phases, agents, rules in force, known limits.
8. In `harness/`: run `tests/hygiene.sh` and `npm test`. Red: fix or revert the edit. Never commit red.
9. Commit, message stating the change without any client name. Run `harness/bin/tag-push <slug>`: it tags, pushes the branch, then the tag, and deletes the tag when the branch push is refused. Refused: pull, redo step 4 on the new commits, resolve each conflict by reading the remote change against your intent (drop yours when covered, combine when compatible, never a blind merge), rerun step 8, run it again. Third refusal: write the pending diff into `retro.md` under `UNPUSHED`.
10. Write `product/features/<slug>/retro.md`: findings, edits made, frictions dropped, open questions.

Rollback is Ali's: `harness/bin/rollback`.
