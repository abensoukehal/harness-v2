---
name: communicate
description: The message shape, the ask format, the pushed events and the end-of-run report.
---

# Communicate

Write every message for someone who was not watching. Feature vocabulary. Above the `Detail:` line: no file name, function name, stack trace, internal name or reasoning trail. Always say what is still running. Readable from a phone in ten seconds.

## Message
The ask is an object; `harness/bin/ask <slug> <sub-task>` renders it. Fields: `where` (one sentence), `stuck` (two or three plain sentences), `tried` (at most two lines), `question` (closed), `options` (two or three, lettered A B C, exactly one `recommended`), `still_running`, `detail` (one path, written from the workspace root, never absolute). No path and no file name outside `detail`. Rendered:
```
<where>

<stuck>

Tried: <line>
Tried: <line>

<question>
A. <text> (recommended)
B. <text>

Still running: <what continues meanwhile, or "nothing">
Detail: <path to the feature folder>
```
A report is never a question: end with what happened, drop the options block, keep `Still running` and `Detail`.

## Pushed events
Three events reach the chat from `notify.telegram`: plan ready, run finished, needs answer. Nothing else pushes. A failed send goes to `frictions` in `state.json`; the run continues.

## End-of-run report
```
<feature> — <done | done with gaps | partial | nothing landed>

What works now.
<plain sentences: what he can go and try>

What didn't land.
<blocked and skipped sub-tasks, one line each, plain words>

Assumptions I made.
<one plain line each, the decision taken; the reasoning stays in spec-gaps.md>

What it cost.
<tokens, wall time, sub-tasks, attempts, against the last three runs>

Next.
<the branch to open a PR on, or what needs deciding first>

Detail: <plan.md> <decisions.md> <state.json> <gaps/>
```
`bin/cost` reads the runtime's transcripts, input tokens included, and `bin/report` appends one line to `product/cost-log.md`: `<slug> | <tokens> | <wall_time_s> | <subtasks> | <blocked>`.

Reactions from Ali ("I don't understand", "which task?") go to `frictions`.
