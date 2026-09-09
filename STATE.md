# State of the engine

## What it is
A project-agnostic engine that implements one feature at a time in client repos it does not own. Three workflows, `/harness-plan`, `/harness-build`, `/harness-retro`, orchestrate subagents; every filesystem and shell step runs inside an agent through `bin/` tools; `lib/harness/` holds the mechanics; `schemas/` holds the config, state and worker result contracts.

## Phases
1. Ingestion and planning: the planner writes `code-map/`, `conventions.md`, `plan.md`, `spec-gaps.md`, `journey.md`; `plan_ready` is pushed.
2. Safety net: client baseline, regression tests under `product/tests/`, mutation check, freeze.
3. Build: per sub-task a worker, a reviewer, a commit; rounds come from `bin/next`; a restart request is served twice per sub-task.
4. QA and delivery: journey, net, baseline diff, visual diff, bounded fixes, then the push. Both run only when at least one sub-task landed; otherwise the run records `delivered: false` and reports partial.
5. Retro: in its own clone of the engine remote, tests, tag, push.

## Agents
planner, test-writer, worker, reviewer, qa, retro. Skills: criteria-runner, visual-diff, commit-hygiene, reduce, communicate, retro.

## Rules in force
- The workspace root is passed, never resolved from a working directory.
- Every spawn is retried once; a second refusal is a friction carrying the runtime's reason, `reason: runtime`, no attempt spent.
- Schemas handed to `agent()` are inline, in the dialect the runtime accepts: no `$schema`, `$ref` or conditionals. The files under `schemas/` stay the full contract and `bin/validate` and `bin/state` enforce them.
- Model and effort per role are config (`agents:` in `client.config.yaml`), static per workspace, passed to every spawn in all three workflows; `bin/agents` resolves them.
- Cost comes from the runtime transcripts: input tokens per agent, counted only for agents whose first message names both the feature and the workspace path, with the model and effort that spent them.
- A relaunch still inside the safety net rebuilds and refreezes it; the net check refuses an unfrozen net only past that phase.
- `harness/` in a workspace runs the pinned commit only; the retro never moves it.

## Known limits
- Every mechanical step is a subagent that loads the full context; see OPEN_QUESTIONS.md.
- The push to the engine remote needs a remote that accepts branch pushes.
- No browser runner ships with the engine; screen checks need one in the client config.
