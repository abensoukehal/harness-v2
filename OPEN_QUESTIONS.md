# Open questions

## A new agent role needs a session that starts after its file exists
The runtime registers `claude/agents/*.md` when a session starts, so a role added during a session cannot be spawned in that session: `agent({agentType})` refuses with the role unfound, and no relink or file write registers it mid-run. A retro that adds a role therefore cannot exercise it until the next run, which is the normal order and costs nothing — but a change verified in the same session it was written will look broken when it is not. Decide whether `bin/link` should say so, or whether the retro's own check should refuse a role the running session cannot resolve.


## A refused spawn is respawned without asking whether the first one landed its work
The runtime refuses a spawn after its agent has already written its files, and the retry in the `retrying` block opens a worktree where the edit, the decisions and the code map are in place. The second agent re-verifies instead of implementing and the run pays for the sub-task twice, while `attempts` stays 1, so the duplication does not show in `state.json`. The shape of the fix: the second call declares itself a retry whose predecessor may have landed, checks the worktree before it works, and counts the duplicate pair. It waits in `product/frictions.md` under `retry-respawn-redoes-landed-work`, count one, and the engine changes on a second run.


## A part of a multi-part instruction can go missing with nothing to notice
An instruction that arrives in several parts is answered in one report, and a part that never reaches the code leaves no trace in this repo: three changes were asked for in one message, two were built and reported, and the third was found two runs later by a check written for something else. The inventory test covers half of the shape — a measurement that reaches `SPEC.md` and not the schema fails it — and nothing covers a part that never reaches the spec at all. The engine cannot see the instruction, only what the instruction became, so a counter here would count what a human chose to write down. Decide whether the report that answers a multi-part instruction has to enumerate the parts it received, or whether the spec is the only ledger and a part that never reaches it is accepted as lost.
