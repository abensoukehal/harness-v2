# Open questions

## A new agent role needs a session that starts after its file exists
The runtime registers `claude/agents/*.md` when a session starts, so a role added during a session cannot be spawned in that session: `agent({agentType})` refuses with the role unfound, and no relink or file write registers it mid-run. A retro that adds a role therefore cannot exercise it until the next run, which is the normal order and costs nothing — but a change verified in the same session it was written will look broken when it is not. Decide whether `bin/link` should say so, or whether the retro's own check should refuse a role the running session cannot resolve.


## The engine remote refuses branch pushes
The remote is a working clone with its default branch checked out, so every `bin/tag-push` is rejected and each retro ends UNPUSHED with its diff in `retro.md`. Decide one of: make the remote bare, set `receive.denyCurrentBranch` to `updateInstead` on it, push retros to a side branch that Ali merges, or have `bin/init` refuse a remote of this shape. Until then no retro tag reaches the remote.
