---
name: communicate
description: The message shape, the ask format, the pushed events and the end-of-run report.
---

# Communicate

Write every message for someone who was not watching. Feature vocabulary. Above the `Detail:` line: no file name, function name, stack trace, internal name or reasoning trail. Always say what is still running. Readable from a phone in ten seconds.

## Message
```
<Where we are. One sentence.>

<What's stuck. Two or three plain sentences.>

Tried: <one line>
Tried: <one line>

<What I need. A closed question.>
A. <option> (recommended)
B. <option>
C. <option>

Still running: <what continues meanwhile, or "nothing">
Detail: <path to the feature folder>
```
A report is never a question: end with what happened, drop the options block, keep `Still running` and `Detail`.

## Pushed events
Three events reach the chat from `notify.telegram`: plan ready, run finished, needs answer. Nothing else pushes. A failed send goes to `frictions` in `state.json`; the run continues.

## End-of-run report
```
<feature> — <done | done with gaps | partial>

What works now.
<plain sentences: what he can go and try>

What didn't land.
<blocked and skipped sub-tasks, one line each, plain words>

Assumptions I made.
<from spec-gaps.md and decisions.md, only those that shaped the result>

What it cost.
<tokens, wall time, sub-tasks, attempts, against the last three runs>

Next.
<the branch to open a PR on, or what needs deciding first>

Detail: <plan.md> <decisions.md> <state.json> <gaps/>
```
Append one line to `product/cost-log.md`: `<slug> | <tokens> | <wall_time_s> | <subtasks> | <blocked>`.

Reactions from Ali ("I don't understand", "which task?") go to `frictions`.
