---
name: retro
description: The retrospective as a checklist, from frictions to a pushed and tagged engine.
---

# Retro

Engine edits go into the engine clone the orchestrator names, a fresh clone of the harness remote. The workspace's `harness/` is never edited, pulled or checked out. Product writes: `retro.md` and `conventions.md` only.

1. Read `state.json`: frictions, blocked items, attempts and interruptions, cost per sub-task, budget overrun, accepted gaps, reactions from Ali.
2. Compare this run's totals with the median of the previous three runs in this workspace's `cost-log.md`: tokens, wall time, blocked count, interventions, attempts per sub-task. Fewer than three runs: one line saying there is no baseline. Any total more than 50% worse with no matching growth in feature size: write it at the top of `retro.md` as a suspected regression, name the harness commits between `harness_commit` and HEAD, add an entry to `OPEN_QUESTIONS.md`. Decide nothing about the cause.
3. In the clone, read `git log <harness_commit>..HEAD` with diffs.
4. Drop every friction a commit in that range already addresses.
5. Generalise each remaining friction: strip client, repo, service, domain, person, endpoint, table and branch names. A friction that cannot be stated without them goes to `product/conventions.md`, not the engine. A friction caused by the workspace's own setup, a missing credential or an unset path, goes to `retro.md` for Ali, not the engine.
6. Per remaining friction, run `harness/bin/friction <cause-slug> <feature> [<category>]` in the workspace. Declare the category when the friction is a false green, a secret out of its file, a delivery that pushed the wrong thing, or a guard stepped past; the four words are `false-green`, `secret`, `delivery`, `guard-bypassed`, and the declared word decides whatever the slug spells. It records the cause in `product/frictions.md` and answers `eligible`. False: leave the engine alone for that friction and name it in `retro.md` as recorded and waiting. True: fix it.
7. Write each fix into the harness file that owns the subject by rewriting the existing rule in place. Add a rule only for a subject no file covers. A fix to a guard carries a test that drives an input the guard refuses; a test asserting the fix is present passes on the defect too. Stay under every file's cap; consolidate at the cap. A file that grew across three consecutive retros while none shrank: entry in `OPEN_QUESTIONS.md`, no edit.
8. Rewrite the clone's `STATE.md` when the engine changed: what it is now, phases, agents, rules in force, known limits.
9. In the clone: run `tests/hygiene.sh --workspace $HARNESS_WORKSPACE` and `npm test`. Red: fix or revert the edit. Never commit red.
10. Commit, message stating the change without any client name. Run the clone's `bin/tag-push <slug>`: it tags, pushes the branch, then the tag, and deletes the tag when the branch push is refused. Refused: pull, redo step 4 on the new commits, resolve each conflict by reading the remote change against your intent (drop yours when covered, combine when compatible, never a blind merge), rerun step 9, run it again. Third refusal: write the pending diff into `retro.md` under `UNPUSHED`.
11. Write `product/features/<slug>/retro.md`: findings, edits made, frictions dropped, open questions.

Rollback and adopting a retro with `bin/pin` are Ali's.
