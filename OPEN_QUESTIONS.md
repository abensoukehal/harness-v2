# Open questions

## A new agent role needs a session that starts after its file exists
The runtime registers `claude/agents/*.md` when a session starts, so a role added during a session cannot be spawned in that session: `agent({agentType})` refuses with the role unfound, and no relink or file write registers it mid-run. A retro that adds a role therefore cannot exercise it until the next run, which is the normal order and costs nothing — but a change verified in the same session it was written will look broken when it is not. Decide whether `bin/link` should say so, or whether the retro's own check should refuse a role the running session cannot resolve.


## A refused spawn is respawned without asking whether the first one landed its work
The runtime refuses a spawn after its agent has already written its files, and the retry in the `retrying` block opens a worktree where the edit, the decisions and the code map are in place. The second agent re-verifies instead of implementing and the run pays for the sub-task twice, while `attempts` stays 1, so the duplication does not show in `state.json`. The shape of the fix: the second call declares itself a retry whose predecessor may have landed, checks the worktree before it works, and counts the duplicate pair. It waits in `product/frictions.md` under `retry-respawn-redoes-landed-work`, count one, and the engine changes on a second run.

## Two recorded numbers have no reader, and the inventory will not delete them alone
`divergence_pct` on an accepted gap and `lines_added` on a sub-task's cost are written on every run and loaded by nothing under `lib/` or `bin/`. The visual-diff skill computes the divergence and files it, and the report shows the gap without it; the build loop spends `lines_added` on the over-budget friction before it stores the value, and the stored copy is read back by nobody. Section 6.2.1 says such a number is deleted, but deleting either changes what the engine writes and the retro is the place that decides that. Either give each one its reader — the divergence in the report's gap line, the line count in the retro's comparison — or drop the field.
