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
- Every answered gap carries `Pinned:`, a sub-task and one of its criteria; `bin/plan` refuses an answer that resolves to no criterion in `plan.md`.
- A stack declares which env keys are secret; the scrubber covers those and no others, on a token boundary. A declared value under 8 characters fails validation by key instead of being substituted.
- `client_tests.<stack>` and `stacks.<stack>.commands.test` are one command, and the cross-field pass refuses a config where they differ.
- A stack's `health` is a list every entry of which must pass, an `http` entry carries a full URL, and a declared `notify` event without its credentials under `secrets/` is a validation failure.
- The budget is `budget.tokens_per_feature` plus `budget.tokens_per_subtask` per sub-task in the plan, both measured; the overrun is counted once, over the run's own total.
- The plan-ready message is rendered from the parsed plan by `bin/review`, with a Mermaid graph beside it; no agent writes it.
- A sub-task carries at most five criteria, one stack, and dependencies declared by id; the parse refuses a cycle.
- The retro changes the engine on a first friction only for four causes, declared to `bin/friction` as a category rather than spelled out of the cause slug; the rest sit in `product/frictions.md` until a second run.
- A guard's test drives an input that reaches the refused branch; a guard no input can reach is made reachable or removed.
- A workflow script decides nothing inline: its branches sit in the decisions block, and each one is called from a test with both inputs.
- `hygiene.sh` fails a commit that puts the instruction corpus past 40,000 characters; the corpus counts the markdown and the prompt text inside the workflow scripts.
- Cost is two numbers: the per-turn total and the distinct context beside it. Both are in `cost_by_agent`, the by-role line and `cost-log.md`.
- Every mechanical spawn names `agentType: 'io'`, and commands with no agent between them travel in one batch that names which command refused.
- `harness/` in a workspace runs the pinned commit only; the retro never moves it.
- `base_branch` and `target_branch` are one branch for every repo or a map keyed by repo; a map names every repo the stacks live in, and the worktree, the delivery diff, the push and the pre-push hook each resolve the repo they are working in.

## Known limits
- Every mechanical step is a subagent that loads the full context; see OPEN_QUESTIONS.md.
- No browser runner ships with the engine; screen checks need one in the client config.
