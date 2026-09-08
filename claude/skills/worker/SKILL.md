---
name: worker
description: The sub-task loop every implementation worker follows, from briefing to report.
---

# Worker

The briefing holds everything: technical profile, conventions, and the mission with goal, files, criteria, line budget, token budget and dependents. Work from it alone.

## Rules
- Open only the files the mission lists. Need another one: stop and report `NEEDS: <path> · <why>`.
- Grep for the symbol, read about 50 lines around it. Read a whole file only under 150 lines.
- Keep tool output short: the failing assertion and ten relevant lines; build errors only.
- Stay inside the token budget. At the budget, stop and report BLOCKED with `reason: budget` and the partial state.
- No new file, no new abstraction layer, no new dependency without a one-line justification in the report. Extend what exists.
- Grep the module's existing helpers before writing one.
- Replace a path: delete the old one in the same sub-task.
- Never edit a file under `product/tests/`. A test that looks wrong: stop, report BLOCKED with `reason: oracle`.
- Never start or stop a stack. Need a restart: say so in the report.
- Take every decision the plan leaves open, execute it, record it in `decisions.md`: `<id> · <decision> · <source>`. Source: spec, design, an existing pattern with its file, or own judgement with its reasoning in a few words. Never present judgement as spec.
- What you learn about the code goes to `code-map/` or `conventions.md`, never into a later message.

## Loop
1. Implement the goal in the listed files, following the conventions.
2. Run the criteria with the criteria-runner skill.
3. Green: report. Red: fix and rerun. Third red: report BLOCKED with the last ten useful lines.

## Report
Three or four lines: status (`done`, `blocked`, `needs`), files touched, decisions taken, frictions met. Add the line count against the budget.
