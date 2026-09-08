# Open questions

## Cost of the mechanical steps
Every tool call in a workflow runs through a subagent that loads the full session context: about 100k input tokens per step at cache-read weight, thirty to forty steps per feature. The mechanical steps alone pass `budget.tokens_per_feature` before the first worker starts, so the budget flags every run and enforces nothing. Decide one of: count uncached input only, batch the mechanical steps into fewer agents, or set the budget per role. The retro takes none of these on its own.

## The engine remote refuses branch pushes
The remote is a working clone with its default branch checked out, so every `bin/tag-push` is rejected and each retro ends UNPUSHED with its diff in `retro.md`. Decide one of: make the remote bare, set `receive.denyCurrentBranch` to `updateInstead` on it, push retros to a side branch that Ali merges, or have `bin/init` refuse a remote of this shape. Until then no retro tag reaches the remote.
