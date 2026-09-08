---
name: reduce
description: The reduction pass at the end of every sub-task.
---

# Reduce

Run after self-review, before the final criteria run. One mission: remove what the sub-task does not need.

Delete:
- an abstraction or wrapper with one caller
- defensive handling on a path the spec does not name
- a comment that restates the code
- unused config, unused imports, dead branches
- a replaced path left next to its replacement
- a helper duplicating one already in the module; grep first

Keep: what a criterion or the safety net needs, what the spec names.

Count added lines against `line_budget`. Over by more than half: write one line per remaining block saying what it is for, into the report.

Rerun the criteria and the safety net. Both green is the exit.
