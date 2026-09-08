# Harness v2: autonomous feature implementation engine

Spec for Claude Code. Build this as a fresh project. Do not reuse the current harness code, only its lessons.

## 0. What this is

A project-agnostic engine that takes a design plus a spec, and implements a complex feature in a client's legacy repos (frontend, backend, mobile, AI) end to end, autonomously, over a full working day, without breaking existing behavior and without burning the token budget.

It runs on Claude Code. It lives in its own repo. It works on client code that it does not own, and it leaves no trace of itself there.

## 1. Pillars

Every design decision must serve one of these. If it serves none, drop it.

1. **Verifiability.** Everything is a loop with a machine-verifiable exit criterion. "Done" is proven by a test, a browser check, a log line, or a visual diff. Never declared.
2. **Autonomy.** Runs a full-day feature across all stacks without asking to continue. Includes self-improvement: the harness fixes its own frictions after each feature, without human review.
3. **Non-regression.** Starts on legacy code. Writes regression tests before touching anything. Never ships a broken existing behavior.
4. **Context economy.** Tokens are the scarce resource. Thin orchestrator, disposable workers, no exploration, targeted reads, budgets.
5. **Confidentiality and multi-client.** Harness and product layers stay with Ali. Client repos receive only feature code with human-looking commits. Clients are isolated from each other.
6. **Pipeline.** Fixed phases, fixed order, readable progress at any moment.
7. **Communication.** Everything the harness says to Ali is written for someone who was not watching. Feature vocabulary, no internal names, no reasoning trail, always states what is still running. A message he cannot answer in ten seconds from his phone is a defect, and it is recorded as one.

## 2. Three layers

```
harness   → the engine. Project-agnostic. Knows nothing about any client.
product   → Ali's layer per client. Docs, tests, code map, decisions, delivered features. Never shipped.
client    → the client's stacks (their repos). Receives feature code only.
```

### 2.1 Repos and workspaces

- `harness` is one git repo, hosted remotely (GitHub). Single source of truth. Both Ali's PC and the VPS pull from it.
- One **client workspace** per client. A workspace is a directory that contains:

```
<client-name>/
  CLAUDE.md              ← the ONLY CLAUDE.md. Harness entry points, points to config.
  .claude/
    workflows/ agents/ skills/   ← linked from harness/claude/ (see 2.2)
  harness/               ← the harness repo, at the pinned commit (see below)
  secrets/               ← client credentials. Outside git. Never read by an agent (9.3)
  product/               ← Ali's product layer for THIS client (its own private git repo)
    client.config.yaml
    conventions.md
    code-map/
    tests/               ← the safety net and criteria tests. Frozen after phase 3
    cost-log.md          ← one line per completed feature (6.2)
    features/
      <feature-slug>/
        spec.md
        design/          ← exported screens and regions (ui and mixed features only)
        plan.md          ← the plan Ali reads and edits. Source of truth (4.2)
        spec-gaps.md
        journey.md       ← the QA journey script (phase 2)
        state.json
        decisions.md
        retro.md
        gaps/            ← screenshot pairs for ACCEPTED_GAP items
  repos/
    <repo>/              ← client repo checkouts, one per git remote. A repo may hold
                           several stacks (monorepo). Config maps stack → repo
  .worktrees/
    <feature-slug>/<repo>/   ← the working tree a run actually builds in (11.2)
```

- Isolation rule: a session in `<client-name>/` may read only inside `<client-name>/`. No path outside. Client 2 does not exist from inside client 1's workspace.
- Two machines on the same client at the same time is avoided by Ali. If it happens, it's on two different features, hence two different state files and two different branches. No shared mutable state between machines except the harness repo itself (see section 14).

### 2.2 How the harness reaches Claude Code

Claude Code loads workflows, agents and skills from `.claude/` in the working directory. The harness repo ships them under `harness/claude/{workflows,agents,skills}`. The workspace's `.claude/` links to those. A `harness/bin/link` script creates the links. Updating the harness = `git pull` in `harness/` and `/reload-skills`.

No `CLAUDE.md` inside any client repo. Ever.

## 3. Client config

`product/client.config.yaml`. The harness knows only this schema. Adding a client = adding a workspace with this file.

```yaml
client: acme
stacks:
  frontend:
    repo: frontend
    path: repos/frontend
    framework: nextjs@14
    package_manager: pnpm
    commands:
      install: pnpm install
      dev: pnpm dev --port ${PORT_FRONTEND}
      build: pnpm build
      lint: pnpm lint
      typecheck: pnpm tsc --noEmit
      test: pnpm test
    env_file: .env.local        # resolved from workspaces/<client>/secrets/, never inline
    dev_url: http://localhost:${PORT_FRONTEND}
    depends_on: [backend]
    health:
      log: "ready on"
    health_timeout_s: 120
  backend:
    repo: backend             # git repo this stack lives in; several stacks may share one
    path: repos/backend
    framework: django@5
    commands:
      install: pip install -r requirements.txt
      dev: python manage.py runserver 0.0.0.0:${PORT_BACKEND}
      test: pytest
      lint: ruff check .
    dev_url: http://localhost:${PORT_BACKEND}
    logs: stdout            # or a file path, or a docker container name
    depends_on: [db]        # start order; every name here must be a declared stack
    health:                 # ready means this passes, not that the process exists
      http: ${PORT_BACKEND}/healthz
      expect_status: 200
    health_timeout_s: 180
    seed: python manage.py loaddata fixtures/seed.json
  db:                       # infrastructure is a stack. Anything the run starts,
    repo: null                # waits for, or tears down is declared here, or it
    path: null                # cannot be a start-order dependency
    commands:
      dev: docker compose up -d postgres
    health:
      tcp: ${PORT_DB}
    health_timeout_s: 60
  # mobile, ai: same shape, optional

delivery:
  base_branch: develop      # branch to start from
  target_branch: develop    # branch the PR/merge goes to
  branch_prefix: feature/
  mode: pr                  # pr | direct_merge
  commit_author:
    name: Ali <last name>
    email: ali@...

git:
  identity_hygiene: strict  # enforces section 9 rules

notify:
  telegram:
    chat_id_ref: telegram_chat_id   # resolved from secrets/, never inline
  events: [plan_ready, run_finished, needs_answer]

client_tests:                       # the client's own suite, run for the baseline
  backend: pytest
  frontend: pnpm test

test_runner:
  # how Ali's tests (product/tests) import and run against the client checkouts
  frontend: playwright      # e2e via browser
  backend: pytest --rootdir=product/tests/backend
```

Required per stack: `commands.dev`, `health`, `health_timeout_s`. Phases 4 and 5 need every stack running and need to know when it is ready, so a stack missing any of the three fails validation instead of failing at hour two.

`repo` and `path` are null together or not at all, and only for a stack the harness starts but never edits, such as a database container. A repo-less stack gets no worktree and runs from the workspace root, and a plan sub-task cannot target one. A sub-task that needs to change it is a client infrastructure change, which is not something this system delivers.

Validation runs in two passes: schema first, then cross-field checks (paths under their declared repo, `depends_on` names exist and do not cycle, `${PORT_*}` references resolve, test keys are declared stacks, worktree paths match `.worktrees/<feature>/<repo>`). Cross-field checks only run once the schema pass is clean, so a badly broken file takes two rounds to fully diagnose. That is the right order, and the validator says which pass it is reporting.


budget:
  tokens_per_feature: 2000000   # overrun is a harness defect, not a stop

qa:
  max_fixes: 10                 # phase cap; past it, deliver with documented gaps

visual:
  threshold_pct: 2.0        # max divergent pixels per component region
  viewport: 1440x900
  max_attempts: 4
```

The harness never special-cases a client. It reads fields and executes.

## 4. Pipeline

Six phases. Each phase has inputs, outputs, and an exit criterion. Phases run as Claude Code workflows (section 15). The plan validation is the only human checkpoint, so the pipeline is split into three workflows: `plan`, `build`, `retro`.

### 4.0 Feature kinds

Not every feature has screens. The plan sets `kind` on the feature and it switches steps on and off. Nothing else in the pipeline changes.

| kind | design required | visual diff | browser criteria |
|---|---|---|---|
| `ui` | yes | yes | yes |
| `service` | no | no | only if an existing screen consumes it |
| `mixed` | for the screens it touches | those screens only | yes |

- A `service` feature with no design skips design ingestion and the visual diff step entirely. It does not skip QA: the end-to-end journey is replayed through the API instead of the browser.
- The kind is set at plan time and appears in `plan.md`. A feature that turns out to touch screens mid-build is a plan error, and it surfaces as a `NEEDS:` from the worker rather than a quiet widening.

### Phase 1: Ingestion (targeted)

Inputs: `spec.md`, `design/` (Figma export or Claude Design export as images plus any structured data), `client.config.yaml`, `conventions.md` and `code-map/` if they exist from previous features.

Work:
- Read the spec and design. Extract the user-facing outcomes and the pain points being solved.
- Identify which stacks and which zones of each stack the feature touches. Only those.
- Map those zones: entry points, existing patterns, existing test coverage, data models involved. Write it to `code-map/<zone>.md`. Reuse existing map files, update them, never rewrite from scratch.
- Learn conventions from the touched code (naming, error handling, service patterns). Write/update `conventions.md`.

Output: updated `code-map/`, `conventions.md`, and a short ingestion summary in `state.json`.

Exit: every stack listed in the plan has a map file and the summary names the files each sub-task will touch.

No full-repo scan. If a zone isn't in the design or spec, it isn't mapped.

### Phase 2: Planning

Work:
- Derive sub-tasks from design plus spec. Each sub-task is small (one agent, one context, well under budget).
- Each sub-task has: `id`, `stack`, `goal` (one sentence, feature vocabulary), `files` (exact list to open), `depends_on`, `exit_criteria` (machine-verifiable, see section 5), `line_budget` (estimated added lines).
- Order by dependency. Backend before frontend that consumes it, etc.
- Write the QA journey as a runnable script in `journey.md`: the end-to-end path a user takes through the feature, step by step, with the observable result of each step. Phase 5 executes this, not a paraphrase of the spec. For a `service` feature the steps are API calls; for `ui` and `mixed` they are browser actions.
- Write `plan.md`. It is the only place the plan lives.

- Audit the spec while planning. Every time a sub-task needs a fact the spec and design do not state, write the question and the answer the planner chose into `spec-gaps.md`: what was missing, what was assumed, and what it affects. This is not a blocker list, it is a disclosure list.

- Keep the plan bounded: **20 sub-tasks maximum**. A feature that needs more is more than one feature, and saying so at the checkpoint costs a conversation. Discovering it at hour four costs the run.

Exit: `plan.md`, `spec-gaps.md` and `journey.md` written. **Workflow ends here.** Ali reads them, edits the plan or answers gaps, and approves. Then he launches `build`.

#### 4.1 The handoff

The plan is the only thing a human touches, so the handoff cannot be ambiguous.

- **`plan.md` is the source of truth.** Ali edits markdown, not JSON, and he edits it freely: reword a goal, drop a sub-task, change a file list, reorder, adjust a criterion.
- `/harness-build` parses `plan.md` at start and writes the sub-task list into `state.json` from it. The plan is never written back to `plan.md` by the build.
- The parse is strict. A sub-task missing a required field, or a criterion that is not one of the kinds in section 5.1, fails the build immediately with the offending line quoted. Failing at second zero is the cheapest possible failure, and a silently misread plan is the most expensive.
- On resume, `state.json` wins for what is already done. `plan.md` is not re-parsed mid-run; editing it during a run has no effect until the next launch.

#### 4.2 Why the gaps list exists

In v1 a silent spec produced a stop, and the run waited for Ali. In v2 the build cannot ask, so a silent spec produces a silent assumption instead. That is worse, not better. The gaps list moves the cost back to the one moment a human is already reading, where answering costs a minute instead of a rerun.

- A gap Ali answers is folded into the plan before build starts.
- A gap he leaves alone stands as the recorded assumption. The build proceeds on it and does not revisit it.
- Gaps that recur across features are a spec-template problem, and the retro says so.

### Phase 3: Safety net

Work:
- **Run the client's own test suite first**, if they have one, on the untouched base branch. Record what is already red in `state.json` as the inherited baseline. Nothing in it is fixed and nothing in it blocks the run, but a test that was green at the start and is red at the end is a regression the harness caused. This is the only coverage of code outside the map, which is where legacy breaks.
- For every zone in the code map, write regression tests in `product/tests/` that pin current behaviour. Backend: unit/integration on existing endpoints and services. Frontend: Playwright on existing flows in the touched screens.
- Run them on the untouched code. A test that fails here was written wrong, and the test-writer fixes it **in this phase only**.
- **Prove the net is not vacuous.** For each zone, break the behaviour the test pins (change a return value, a status code, a rendered field), confirm at least one test goes red, restore. A zone where nothing goes red has no net, and the test-writer rewrites it before the phase can exit. A test suite that cannot fail proves nothing, and an agent writing its own tests produces those by default.

Exit: the client baseline is recorded, the full safety net passes on the base branch, and every zone survived its mutation check.

**The net is frozen after this phase.** Freezing is a commit, not an instruction: `bin/net freeze` commits `product/tests/` in the product repo and records the sha as `net_commit` in state. `bin/net check` runs at every relaunch and refuses when the tree differs, or when sub-tasks exist with no freeze behind them. `/harness-build` refuses to start on that check. No worker, reviewer or QA agent may edit a file under `product/tests/`. A test that looks wrong during build is a BLOCKED sub-task with `reason: oracle`, never an edit. This is what makes the net mean anything; without it the loop reaches green by moving the target.

### Phase 4: Implementation loop

For each sub-task, in dependency order:

```
spawn worker (fresh context, briefing from section 7)
loop:
  implement
  run exit_criteria
  if pass → break
  if attempts == 3 → mark BLOCKED, record why, break
self-review pass (section 4.3)
reduction pass (section 12)
run safety net + sub-task criteria again
commit (section 9 rules)
update state.json
report 3-4 lines to orchestrator
```

If a sub-task is BLOCKED and later sub-tasks don't depend on it, continue. If they do, mark them SKIPPED with the reason and continue with independent ones. Never stop the run for a single blockage.

#### 4.3 Self-review (adversarial)

Not a human-style code review. The worker rereads its own diff hunting for: edge cases not covered by the criteria, missing error handling on the paths the spec cares about, dead code, hardcoded values, and gaps between what was implemented and what the spec asked. Fix what it finds, rerun criteria.

### Phase 5: Global QA

After all sub-tasks:
- Execute `journey.md` end to end against the running stacks. This is a script written at plan time and approved with the plan, not an improvisation from the spec.
- Run the complete safety net plus all sub-task criteria.
- Rerun the client's own suite and diff against the inherited baseline. Anything that went from green to red is a regression, and it is fixed before delivery. Anything red at the start stays out of scope.
- Run visual diff on every screen in the design.
- Fix what fails, same 3-attempt rule per failure, **within a phase budget**: `qa.max_fixes` from the config, default 10. QA is the phase that concludes, not a second build, and an unbounded fix loop after the build is already done is where a run's remaining budget disappears.
- At the cap, stop fixing. Deliver with every remaining failure documented in the end report as a known gap, with what was tried. A branch with three named defects is worth more to Ali than a run that spent its night on the fourth.

Exit: journey passes, safety net green, visual diffs under threshold (or logged as accepted gaps after max attempts).

Then: delivery (section 10).

### Phase 6: Retrospective

See section 14. Runs as its own workflow.

## 5. Verifiability

### 5.1 Exit criteria format

Each criterion is a command or a check the harness can run and get a boolean from. Allowed kinds:

- `test`: a test file/pattern in `product/tests/` that must pass.
- `http`: method, url (using `${PORT_*}`), expected status, optional JSON path assertion.
- `browser`: Playwright script in `product/tests/`, must pass. Selectors, not screenshots, for functional checks.
- `log`: a regex that must (or must not) appear in the stack's logs after an action.
- `visual`: component region id + reference image, diff under `threshold_pct`.
- `lint`/`typecheck`: the config's command exits 0.

Forbidden: any criterion that reads like "looks correct", "works as expected", "matches design". If it can't be run, it isn't a criterion.

### 5.2 Visual diff

- Reference: design exported as PNG per screen, plus a regions file mapping component ids to bounding boxes.
- Rendering environment is frozen: fixed viewport from config, animations disabled via injected CSS, fonts preloaded, seeded test data, no timestamps rendered.
- Compare per region, not whole screen. Report per-region divergence.
- Max attempts from config (default 4). After that: log the remaining gap with a screenshot pair in the feature folder, mark ACCEPTED_GAP, move on.

### 5.3 Non-deterministic sub-tasks

An LLM output is not a boolean, so a sub-task carrying an examples criterion cannot take a criterion in the form above. The contract rides on the criterion, not on which agent runs it. It does not get an exemption either. It gets a different contract, and the plan marks which one applies.

Split the work, because most of an AI sub-task is ordinary code:

- **Plumbing is deterministic and takes normal criteria.** The endpoint exists, the prompt is assembled from the right fields, the response is parsed, the error path returns what the spec says, the token budget is enforced. This is most of the diff and it is verified like anything else.
- **Behaviour takes an example set.** The plan ships a fixed set of inputs with expected properties, written during planning alongside the sub-task. A property is checkable: the answer names the right protocol, the JSON validates against the schema, the refusal fires on out-of-scope input. Not "the answer is good".
- The criterion is a pass rate over that set with a floor from the plan, run with temperature pinned and the set seeded. Below the floor, the sub-task fails and retries like any other.
- **The floor is never 100%.** A sub-task whose behaviour must be exactly right every time is a sub-task that should not be an LLM call, and the plan says so instead of pretending.
- Failures are recorded as the failing examples, not as a score. A score tells the next attempt nothing.

If the behaviour cannot be expressed as properties over examples, it is not a build sub-task. It goes to Ali as a design question at plan time, in `spec-gaps.md`.

### 5.4 Failure policy

Three attempts per sub-task criterion. On the third failure: BLOCKED, reason recorded in `state.json` with the last error (truncated to ~10 useful lines), and the run continues. Ali sees blocked items in the final report and in the communication protocol (section 13).

## 6. Context economy

Non-negotiable rules.

1. **Orchestrator holds only plan and state.** It never reads source files. It never sees a worker's transcript. It receives a 3-4 line report per sub-task.
2. **Workers are disposable.** Fresh context per sub-task. Briefing contains everything they need. They die after reporting.
3. **No exploration by workers.** The briefing lists exact files. A worker that needs a file not in its list reports `NEEDS: <path> because <reason>` and stops. The orchestrator decides (add file, respawn) rather than letting the worker wander.
4. **Read slices, not files.** Grep for the symbol, read ~50 lines around it. Whole-file reads only for files under 150 lines.
5. **Truncate tool output.** Test failures: the assertion and the 10 relevant lines. Never full stack traces. Build output: errors only.
6. **Budget per worker.** Token budget in the briefing, defaulting to the feature budget divided by the sub-task count and overridable per sub-task in state. Worker exceeds it → stops, reports partial state as BLOCKED with `reason: budget`.
7. **Budget per briefing.** `budget.briefing_chars` caps assembled size. Over the cap, assembly refuses and names both the cap and the size of the conventions file that pushed it over, because that file is nearly always the cause and the fix is a reduction pass, not a larger cap.
7. **Knowledge goes to files, not context.** What a worker learns about the code goes to `code-map/` or `conventions.md`, not into its running context for later.
8. **No context chaining.** One `CLAUDE.md` at workspace root, short. Stack knowledge is loaded on demand by the ingestion phase, never imported permanently.
9. **Avoid compaction.** Compaction means tokens were already wasted. Design so it isn't needed.

### 6.1 Product layer hygiene

`conventions.md` and `code-map/` are enriched on every feature and loaded into every briefing. Unbounded, they become v1's problem one floor down: files nobody can afford to read, paid for on every spawn.

The rules from sections 20.2 and 20.3 apply to them, plus:

- Each file has a size cap. At the cap, ingestion consolidates instead of appending: merge overlapping entries, drop what no longer matches the code.
- A code map entry is a description of the code as it is now. No history, no "this used to be", no dates, no feature slugs.
- An entry describing code that no longer exists is deleted the next time that zone is ingested. Ingestion verifies before it trusts.
- A convention is written once. A second feature that observes the same convention does not add a line.
- `hygiene.sh` runs over the product layer too, with the same word list.

### 6.2 Measurement

Rules with no counter behind them are a wish. The whole reason for v2 is that a feature costs two to three five-hour windows, so the cost is a tracked number, not an impression.

- Per sub-task, `state.json` records: `tokens_in`, `tokens_out`, `attempts`, `duration_s`, `lines_added`.
- Per run, the end report (section 13.2) totals them and breaks them down by phase and by agent role.
- `product/cost-log.md` keeps one line per completed feature: slug, total tokens, wall time, sub-task count, blocked count. Append-only, and the only file in the product layer that is allowed to be a log.
- The retro compares this run against the last three. A phase whose share grew without the feature growing is a friction to name.
- A run that exceeds `budget.tokens_per_feature` from the config does not stop. It flags the overrun in the report and the retro treats it as a defect in the harness, not in the feature.
## 7. Agents

Agents are defined by **role**, not technology. The catalogue lives in `harness/claude/agents/`:

- `planner`: phases 1-2.
- `test-writer`: phase 3, and criteria test files.
- `worker`: phase 4 implementation. **One agent, not one per stack.** With the role, the stack commands and the behaviour contract all arriving in the briefing, four stack-named workers were four copies of one file, which is how v1 reached 370,000 characters of doctrine. The stack is an input, not an identity.
- `reviewer`: self-review and reduction pass (can be the same worker, second prompt, or a separate agent for a cleaner adversarial stance).
- `qa`: phase 5.
- `retro`: phase 6.

Each agent file is a skeleton: role, method, output format, exit conditions. Zero technology-specific content.

### 7.1 Briefing assembly

At spawn time the orchestrator builds the worker prompt from three blocks:

1. **Technical profile** from `client.config.yaml`: framework, version, commands, paths, dev URL, ports.
2. **Learned conventions** from `product/conventions.md`, filtered to the stack.
3. **Mission** from `state.json`: sub-task goal, exact file list, exit criteria, line budget, token budget, and what depends on this sub-task.

Which agents get activated is decided by which stacks appear in the plan. A client without mobile never spawns `mobile-worker`.

## 8. State and memory

`product/features/<slug>/state.json`:

```json
{
  "feature": "checkout-coupons",
  "harness_commit": "<sha at run start>",
  "branch": "feature/checkout-coupons",
  "ports": { "frontend": 51023, "backend": 51024 },
  "phase": "build",
  "subtasks": [
    { "id": "st-01", "stack": "backend", "status": "done", "commit": "<sha>",
      "files": [], "worktree": ".worktrees/checkout-coupons/backend",
      "exit_criteria": [ { "kind": "test", "run": "...", "expect": "..." } ],
      "attempts": 1, "interruptions": 0,
      "cost": { "tokens_in": 0, "tokens_out": 0, "duration_s": 0, "lines_added": 0 } },
    { "id": "st-02", "stack": "frontend", "status": "blocked", "reason": "oracle",
      "attempts": 3, "interruptions": 0 }
  ],
  "client_test_baseline": { "backend": ["<already red at start>"] },
  "decisions": ["..."],
  "frictions": ["..."],
  "accepted_gaps": []
}
```

Rules:
- Updated after every sub-task, and again at every phase boundary.
- `harness_commit` is mandatory. The retro needs it.
- **Exit criteria live here in full, not as a reference to `plan.md`.** Section 4.1 forbids re-parsing the plan mid-run, so a resumed run that only held a pointer would have nothing to verify against.
- **No timestamps anywhere.** Durations only (`duration_s`, `wall_time_s`). A date in machine state fails the hygiene check for a reason that has nothing to do with the run.
- **Two counters, not one.** `attempts` counts criterion failures and caps at 3 (section 5.4). `interruptions` counts crashes on the same sub-task and caps at 3 independently (section 8.3). A run that died twice has spent no attempts.
- **A sub-task still marked running when the loop comes back around is blocked with `reason: error`**, so the run continues past it rather than waiting on a worker that is not coming back. It is `resume` that repairs it: back to pending, one interruption counted, no attempt spent. Blocking it in the loop keeps the day going; counting it as a failed attempt would spend the sub-task's budget on a crash it did not cause.
- `delivered` records whether the feature reached the client branch. The report's partial status reads it.

### 8.1 Starting a feature

`harness/bin/new <slug>` creates `product/features/<slug>/` from a template: an empty `spec.md` with the section headings the planner expects, an empty `design/`, and nothing else. Ali fills the spec and drops the design export in. Then `/harness-plan <slug>`.

Everything else in the folder is written by the harness. If a file the pipeline owns already exists when a phase starts, that phase is being rerun, and it says so rather than overwriting silently.

### 8.2 Feature folder

`product/features/<slug>/` holds everything the run produces:

```
spec.md            what Ali wrote
design/            exported screens and regions
plan.md            sub-tasks, human-readable
spec-gaps.md       what the spec did not answer, and what was assumed
state.json         machine state, the restart point
decisions.md       one line per decision taken during build
retro.md           written by the retro workflow
gaps/              screenshot pairs for ACCEPTED_GAP items
```

`decisions.md` format, one line each: `<sub-task id> · <the decision> · <the source>`. Source is one of: spec, design, an existing pattern in the client code (with the file), or the agent's own judgement with a stated reason. Judgement is allowed. Presenting judgement as spec is not. Ali reads this file after the run; wrong calls become plan-phase criteria next time.

### 8.3 Crash and resume

The VPS runs unattended, so a run dies mid-way sooner or later. `harness/bin/resume <slug>` is the only entry point, and it never guesses.

- A sub-task is atomic. It is done when its commit exists, and nothing else counts as done.
- On resume: read `state.json`, then verify it against reality rather than trusting it. Check the branch head, check which sub-task commits exist, check whether the recorded ports are still held.
- Reality wins on every disagreement. A sub-task marked `done` with no commit is reset to `pending`.
- Reset the interrupted sub-task fully: `git checkout -- .` and `git clean -fd` in its worktree, drop the partial work, respawn from the briefing. Never resume a worker's context; there is none to resume.
- Ports recorded in state are released if the harness still owns them, and **reallocated if anything else holds them**. A port taken by a process the harness never started cannot be released, only avoided, and a resume that insists on its old port fails for a reason that has nothing to do with the feature.
- Restart the stacks and rerun the safety net before continuing. A resumed run that skips the safety net is building on an unverified base.
- A run interrupted three times on the same sub-task is BLOCKED with `reason: unstable`, and the run moves on.

## 9. Confidentiality

### 9.1 What may land in a client repo

Only feature code, on the feature branch. Enforced by a path allowlist at commit time: the commit routine refuses any path outside the feature's worktree and refuses any file matching the harness/product patterns (`state.json`, `plan.md`, `retro.md`, `*.harness.*`, `CLAUDE.md`, `.claude/`, test files under `product/`). A refused path fails the commit loudly; it is never silently dropped.

### 9.2 Commits

- Author and committer: from `delivery.commit_author`. Nothing else.
- No `Co-Authored-By`. Any global git config or hook that adds trailers is overridden in the workspace (`git config --local` in each repo, set when that repo's first worktree is created, since the client repos are cloned after the workspace exists).
- Message: a factual description of what was implemented. Imperative, one line, optional short body. Example: `Add coupon validation to checkout form`.
- Forbidden in messages: task ids, feature slugs from the product layer, the words harness/agent/Claude/AI, references to internal files, dates from the run.
- Do not read the client's commit history to mimic style. Just write plain, clear commits.

### 9.3 Client credentials

Running a client's stacks needs their env files, database and service credentials. They are the client's, and they are the one thing in this system that must not travel.

- Credentials live in `workspaces/<client>/secrets/`, outside git, outside the product layer, never in `client.config.yaml`. The config references them by name, not by value.
- The harness injects them into stack processes as env vars at start. No agent ever reads the secrets directory, and no briefing quotes a value.
- Output of stack and seed commands is scrubbed for those values before it enters any context, so a service that echoes its connection string on boot cannot leak it into a transcript.
- **The scrubber covers what the harness runs, not what an agent runs.** A command an agent issues itself in bash reaches that agent's transcript directly, and no layer below can intercept it. What covers that gap instead: agents never read the secrets directory, briefings never quote a value, and every stack command with a secret in it is invoked through the harness rather than composed by an agent. State the limit rather than trusting a guarantee the mechanism does not provide.
- Test data is seeded and fake. A run never touches a client's real database, staging included.
- Deleting a workspace deletes the secrets with it.

### 9.4 Push protection

The commit allowlist controls what goes into a commit. It says nothing about where that commit lands, and a run works unattended in bypass permission mode with `git push` allowed on client remotes. The destination needs a guard, not an instruction.

- Workspace setup installs a `pre-push` hook in every client worktree. It refuses any ref that is not `${branch_prefix}<slug>` for the feature that owns the worktree, and refuses any force-push, unconditionally.
- The hook is the guard. Section 10's rules are what the harness intends; the hook is what happens when an agent intends otherwise.
- `direct_merge` mode is the one exception, and it is narrow: the hook allows `target_branch` only for the delivery step, and only after phase 5 has passed. Nothing else in the run can reach it.
- A refused push fails loudly and is a friction, never a retry with different arguments.

### 9.5 Tests are not a deliverable

All tests live in `product/tests/`. They import the client code by path. Test dependencies and runners are installed in the workspace, never added to the client's dependency files. The client repo does not know the tests exist.

## 10. Delivery

One routine, driven by config:

- Create `${branch_prefix}<slug>` from `base_branch` at run start.
- One commit per validated sub-task (section 9.2).
- At the end of phase 5:
  - `mode: pr` → push the branch, then stop. Ali opens the PR himself and handles the client-side review and merge.
  - `mode: direct_merge` → merge into `target_branch`, push. Global QA is the only gate.
- Never force-push. Never touch `target_branch` in `pr` mode.

### 10.1 After the branch is pushed

The run ends but the feature does not. A client reviewer will ask for changes, and there has to be a way back in that is not "start over".

- The feature folder and its worktree survive delivery. Cleanup stops processes and releases ports; it does not remove the worktree until Ali closes the feature with `harness/bin/close <slug>`.
- Review feedback re-enters as `harness/bin/revise <slug>`, with the requested changes as input. It runs a short pipeline: plan the changes as new sub-tasks, reuse the existing safety net, implement, QA the affected journey only, commit to the same branch. No re-ingestion, no new branch.
- A revision that touches zones outside the original code map is not a revision. It is a new feature against the same branch, and it says so rather than quietly widening scope.
- `close` merges nothing. It removes the worktree, releases anything still held, and marks the feature closed in the cost log. Merging stays a human act on the client side.

## 11. Environment and ports

- Dynamic allocation. At environment start the harness asks the OS for free ports, writes them into `state.json`, and injects them as `PORT_<STACK>` env vars into every command from the config and into the test runner. Nothing assumes a fixed port.
- Each run owns `<workspace>/.run/<slug>/`, holding pid files and captured logs. Nothing else writes there.
- A `logs` file path is resolved against the stack's checkout, or against the workspace root for a repo-less stack, which has no checkout to resolve against.
- Cleanup at feature end (success or failure): stop all processes started by the run, release the ports it holds, remove `.run/<slug>/`. A second cleanup on the same slug is a no-op, not an error. `harness/bin/cleanup <slug>` does the same manually.
- If stacks run in containers, one isolated network per feature, ports mapped outward only.

### 11.1 Bringing the environment up

Phases 4 and 5 need the stacks running. On legacy code a stack can take a minute or more to boot, so a criterion that runs against a half-started service fails for the wrong reason and burns an attempt.

- Stacks start in the order given by `depends_on` in the config. A stack starts only after everything it depends on is ready.
- Ready means a `health` check from the config passed, not that the process exists. One of three kinds per stack: an HTTP endpoint returning an expected status, a TCP port accepting a connection, or a log line matching a pattern. Poll until it passes or `health_timeout_s` elapses.
- `health_timeout_s` has no default. A stack whose boot time nobody has measured is a stack that will fail at the wrong moment, so the config states it.
- A stack that never becomes healthy fails the run at the environment step, before any sub-task starts. Failing there costs one clear error; failing later costs three attempts and a misleading diagnosis.
- Test data comes from a `seed` command per stack, run after health and before the safety net. Seeded and fake, always (section 9.3).
- The environment comes up once per feature run and stays up across sub-tasks. A worker never starts or stops a stack.

**Restarting a stack.** A worker that needs one restarted, typically after a config or dependency change, returns `RESTART: <stack>` in its structured result and stops. It does not run the command itself; a worker with the power to restart infrastructure will use it to work around a problem instead of reporting one.

- The orchestrator calls `harness/bin/restart <slug> <stack>`, which stops that stack, starts it, and reruns its health check. Dependents are restarted with it, in order.
- **A restart does not reseed.** Seeding runs once, at environment startup. A sub-task mid-flight has usually built up data the frozen tests read, and wiping it under a worker that is about to retry means the retry runs against a different world than the attempt before it, for reasons nobody recorded. A worker that genuinely needs fresh data returns `RESTART: <stack> --reseed` and says why in its report; the reseed is written to state so the retro can see which runs had one.
- The port stays the same across a restart, since it is in state and nothing else claimed it.
- The worker is respawned with the same briefing. This does not consume an attempt: the environment failed, not the sub-task.
- Two restarts of the same stack within one sub-task is a BLOCKED sub-task with `reason: environment`. The third would be a loop.

### 11.2 Multi-feature parallelism (in scope for v1)

Several features can run at once inside one workspace. Two runs must never share a working tree.

- Worktrees are created **per git repository, not per stack**. Several stacks can live in one repo (a monorepo is the common case in legacy clients), and `client.config.yaml` says which repo each stack belongs to via `repo`. One worktree per repo the feature touches: `git -C repos/<repo> worktree add ../../.worktrees/<slug>/<repo> -b <branch_prefix><slug> <base_branch>`. Stack paths resolve inside it.
- A monorepo therefore gets one branch and one commit stream for the whole feature, even when the feature spans backend and frontend. Sub-tasks still commit one at a time.
- The worktree paths, not the checkout paths, are what the run's commands and briefings point to. `state.json` records them.
- Ports are allocated per feature (already dynamic), so parallel dev servers don't collide.
- `product/features/<slug>/` is per feature, so state, plan and retro never conflict.
- `product/conventions.md` and `code-map/` are shared and mutable. Concurrent runs append to them through a single-writer lock (`product/.lock`); a run that can't take the lock queues its update to the end of its phase rather than blocking.
- Cleanup removes each worktree (`git worktree remove`) along with the processes and ports.
- Cap concurrent features per workspace in config (`max_parallel_features`, default 2). CPU and the 16-agent runtime cap are the real limits.

## 12. Code verbosity control

A stated instruction is not enough. Three enforced mechanisms:

1. **Line budget per sub-task**, set in the plan. Exceeding by more than 50% is not a failure but forces the reduction pass to justify each remaining block in one line, and the justification goes in the report.
2. **Mandatory reduction pass** at the end of every sub-task loop, after self-review. Single mission: remove what isn't needed. Premature abstractions, defensive handling on paths the spec doesn't care about, obvious comments, unused config, wrapper functions with one caller. Criteria and safety net must still pass after. This is an exit constraint, not advice.
3. **Default prohibitions** in every worker briefing: no new file, no new abstraction layer, no new dependency without a one-line justification in the report. Extend what exists.

## 13. Communication protocol

When the harness needs Ali (blocked plan decision, end-of-run report, anything requiring input), the message follows this shape, in this order, in plain human language:

1. **Where we are.** One sentence, feature vocabulary. "Coupon validation is done on the backend, the frontend form is half way."
2. **What's stuck.** Explained to a colleague who followed nothing. No file names, no function names, no stack traces.
3. **What was tried.** Two lines max.
4. **What I need from you.** A closed question with 2-3 options, answerable from a phone in ten seconds.

"Answerable from a phone" is a property of the text, so it is checked as one rather than asked for politely: no path or file name outside `Detail:`, at most three options, lettered in order, exactly one marked recommended, report under 600 characters, rendered ask under 700. An ask that fails these is refused at the field that failed. This is pillar one applied to the harness's own output: a rule that only exists in prose is a rule that stops holding on a bad day.

Technical detail lives in `state.json` and the feature folder. The message points there once, at the end, if Ali wants to dig.

Ali's reactions ("I don't understand", "reformulate", "which task?") are recorded as frictions and feed the retro. Communication quality is a self-improvement target like any other.

### 13.1 The channel

A run works overnight on the VPS. A message sitting in a file until Ali next opens it caps the whole system at how often he checks, so anything that needs him is **pushed**, not left.

- Telegram, configured per workspace. The message is the four blocks above, nothing more, plus one link to the feature folder.
- Three events push: the plan is ready for validation, the run finished, the run needs an answer it cannot proceed without.
- Nothing else pushes. Not sub-task completions, not blocked items mid-run, not progress. Those land in the end report. A channel that fires often gets muted, and then it is worse than no channel.
- Failure to send never blocks a run. It is a friction.

### 13.2 The end-of-run report

The one artefact Ali reads every feature. Fixed shape, in this order:

```
<feature> — <done | done with gaps | partial>

What works now.            plain sentences, feature vocabulary, what he can go and try
What didn't land.          blocked and skipped sub-tasks, one line each, in plain words
Assumptions I made.        from spec-gaps.md and decisions.md, only the ones that shaped
                           the result — not the whole log
What it cost.              tokens, wall time, sub-tasks, attempts, against the last three runs
Next.                      the branch to open a PR on, or what needs deciding first

Detail: <paths to plan.md, decisions.md, state.json, gaps/>
```

Same rule as section 13: everything technical lives on the `Detail:` line. The report ends with what happened, never with a question about whether to continue.

## 14. Retrospective and self-improvement

Runs as its own workflow after delivery. No human validation. Fully autonomous.

### 14.1 Steps

1. Read `state.json`: frictions, blocked items, attempts counts, budget overruns, accepted gaps, Ali's communication reactions.
2. `git pull` the harness repo. Read `git log <harness_commit>..HEAD` and the diffs.
3. For each friction: check whether a change since `harness_commit` already addresses it. If yes, drop it.
4. For what remains: write the fix directly into the harness files (agents, skills, workflows, rules).
5. Run the harness's own test suite (section 14.6).
6. Commit and push. If push is rejected: pull, re-run step 3 on the new commits, resolve conflicts (section 14.3), re-run tests, push again. Retry up to 3 times, then write the pending changes to `retro.md` as `UNPUSHED` for the next run to pick up.
7. Write `retro.md` in the feature folder (per-feature, so retros never conflict with each other) and append open questions to `harness/OPEN_QUESTIONS.md` (section 16).

### 14.2 The engine carries no client fact

The retro reads frictions from a run on a client's code and pushes the result to a repo every workspace pulls. That is a leak path, and it is the one v1 had to close.

- Nothing the retro writes may name a client, a repo, a service, a domain term, a person, an endpoint, a table or a branch from any client's code.
- A friction is generalised before it becomes an instruction. "The worker got lost in Acme's billing service naming" becomes "when a stack uses more than one naming scheme for the same concept, record both in conventions.md at ingestion". The fix is about the harness; the example stays behind.
- A friction that cannot be generalised without naming the client is not an engine change. It goes to `product/conventions.md` in that client's workspace, which never travels.
- `hygiene.sh` enforces it mechanically: the harness repo is scanned against the client names and stack keys known to the workspace, and a hit fails the retro's commit. Mechanical, because a model asked to check its own writing for leaks will always find the mention essential.

### 14.3 Conflict resolution

The retro agent has the context a merge algorithm lacks: it knows what it wanted to change and why. On conflict it reads the remote version, reads its own intent, and decides: the remote change already covers the need (abandon own change), or the two are compatible (combine them). Never a blind merge. Always rerun harness tests after.

### 14.4 Harness file hygiene

These rules apply to every file the retro touches, and to the initial implementation:

- Files contain only the **current** instruction set. No changelog, no "fixed on <date>", no "we noticed that…". History lives in git commits; the commit message carries the why.
- Instructions are written in the imperative, present tense. "Read only the listed files." Not "Because workers used to explore, now read only the listed files."
- **Edit, never stack.** When a friction concerns a subject that already has an instruction, the retro modifies that instruction. It does not add a new paragraph next to it. Adding a new instruction is allowed only for a subject the file does not cover.
- Every file has a size cap. Approaching it forces consolidation, not a new file.

### 14.5 Rollback

The retro edits the engine with no human review, and its own tests only cover mechanics: schemas, the commit allowlist, port allocation, briefing assembly. They cannot tell whether a rewritten instruction still works. That is only visible on the next feature, which is why there has to be a way back.

- Every retro push is tagged `retro/<slug>` on the harness repo. The tag is the rollback point, and `state.json` already records the harness commit each run started from.
- **The branch is pushed first, and the tag only after that push succeeds.** A tag pushed on its own points at commits the remote holds on no branch: invisible to anyone cloning, un-fetched by default, and still picked up by the rollback search. The next rollback then targets a commit that does not exist locally. Order the two pushes and delete the tag locally if the branch push is refused.
- The first thing the retro does on the next run is compare that run's totals against the median of the previous three **in the same workspace**: tokens, wall time, blocked count, attempts per sub-task. Cost varies more between clients than between harness versions, so a cross-client comparison is noise wearing the shape of a signal.
- Below three runs in the workspace there is no baseline and no comparison. The retro says so in one line rather than reasoning from one data point.
- A run more than 50% worse on any of those, with no matching growth in feature size, is a **suspected regression**. The retro does not decide it caused it. It writes the finding at the top of `retro.md`, names the harness commits in that window, and appends to `OPEN_QUESTIONS.md`.
- `harness/bin/rollback [<tag>]` resets the engine to a previous retro tag, defaulting to the newest `retro/*` tag **strictly behind HEAD**. When HEAD itself carries a tag, that tag is the run being rolled back and the target is the one before it. Ali runs it. Rolling back is a revert commit, never a force-push, so no other workspace loses history.
- A rolled-back change is not retried silently. It goes to `harness/OPEN_QUESTIONS.md`, which the retro creates on first use and never on bootstrap. An empty file that exists is a file every agent loads for nothing. It goes there with what it was trying to fix, so the friction survives even though the fix did not.

### 14.6 Harness tests

The harness has its own test suite: schema validation for config and state, the commit allowlist, the commit message filter, port allocation and cleanup, briefing assembly, the criteria runner for each kind. The retro runs it before every push.

## 15. Claude Code implementation mapping

Use native primitives. Do not build a custom orchestrator in a shell script when Claude Code already has one.

### 15.1 Workflows

Three saved workflows in `harness/claude/workflows/`, exposed in the workspace as `/harness-plan`, `/harness-build`, `/harness-retro`. Split is forced by the runtime: a workflow cannot take user input mid-run, and plan validation is the human checkpoint.

- `/harness-plan <slug>`: phases 1-2. Ends with `plan.md` written.
- `/harness-build <slug>`: phases 3-5 plus delivery. Reads `plan.md` and `state.json`. Resumable: on relaunch, sub-tasks with `status: done` in state are skipped.
- `/harness-retro <slug>`: phase 6.

Inside the scripts:
- `phase('Ingestion')`, `phase('Safety net')`, `phase('Build')`, `phase('QA')`, `phase('Delivery')` so `/workflows` shows exactly where the run is. This is the "clear overview" requirement.
- `agent()` per worker with a `schema` so reports come back structured (status, files, decisions, frictions, needs). The script keeps them in variables; the orchestrator context sees only the final summary.
- The sub-task loop is a JS loop in the script: `for` over ordered sub-tasks, `while attempts < 3`, criteria run by a `qa`-type agent that returns `{pass: boolean, detail: string}`.
- Use `args` for the slug and for a timestamp (the runtime forbids `Date.now()` in scripts).
- Model per stage: strongest model for planner and workers, a smaller model for the criteria runner and log checks if it holds up. Make it a config field so the retro can tune it.
- Keep `workflowSizeGuideline` at `medium`; workers are sequential by dependency, parallel only for independent sub-tasks (cap at 4 concurrent to protect ports and CPU).

Scripts are pure orchestration. All filesystem and shell work happens inside agents.

Before editing any workflow script, load `/workflow-authoring`.

### 15.2 Subagents

`harness/claude/agents/*.md` as described in section 7. Restrict tools per agent: workers get read/edit/bash; the criteria runner gets bash only; the retro gets read/edit/bash on `harness/` only.

### 15.3 Skills

- `criteria-runner`: how to execute each criterion kind and normalize the result.
- `visual-diff`: screenshot, region compare, report.
- `commit-hygiene`: the allowlist and message filter, with the exact commands.
- `reduce`: the reduction pass checklist.
- `communicate`: the four-block message shape.
- `retro`: sections 14.1 to 14.4 as an executable checklist.

### 15.4 Permissions

Auto or bypass permission mode for unattended runs on the VPS; add the config commands (install, dev, test, lint, git push) to allow rules so agents never block on a prompt. Deny rules on any path outside the workspace.

## 16. Artifacts for the Ali ⇄ Claude loop

Two files the harness maintains so a conversation about the harness can start with the current picture without Ali explaining anything:

- `harness/STATE.md`: what the harness is right now, in plain language. Version, phases, agents, rules in force, known limits. Rewritten by the retro when something changes. No history.
- `harness/OPEN_QUESTIONS.md`: things the retro could not decide alone. Each entry: the friction, the options seen, why it couldn't choose. Ali brings these to a discussion; decisions become the next version's changes and the entry is removed.

## 17. Open decisions (v1 defaults, revisit in retro)

- Reviewer as separate agent vs second prompt to the same worker. v1: separate agent (cleaner adversarial stance, costs one extra spawn).
- Criteria runner model. v1: session model; try a smaller one in a later feature.
- Visual region mapping: hand-made regions file vs derived from Figma node tree. v1: hand-made, exported with the design.
- Harness in workspace: submodule vs plain clone pinned to a commit. v1: plain clone plus a pinned sha in `state.json`; simpler on the VPS.

## 18. Out of scope for v1

- Client-side CI integration.
- Any UI beyond `/workflows` and the files in the feature folder.
- Cross-client learning (conventions never cross workspaces by design).

## 19. Definition of done for the harness itself

- A new workspace can be created from a template with `harness/bin/init <client>`.
- **The pin is a file, not a convention.** `product/harness.pin` holds the harness commit the workspace runs. `init` writes it, `link` verifies it, and every workflow refuses to start when `harness/` is at a different commit. Without that check a workspace silently drifts onto whatever the last `git pull` brought, and the harness commit recorded in state describes a run that nobody can reproduce.
- Ali moves a workspace forward with `harness/bin/pin <client> [<commit>]`, defaulting to the harness remote's HEAD. Upgrading is a deliberate act per workspace, so a bad retro cannot reach every client at once.
- Workspaces are found under `--root`, else `HARNESS_WORKSPACES`, else `<harness>/../workspaces`. Same resolution order as `init`, since a command that finds a workspace where another one put it is one less thing to remember.
- **What enforces the pin is the tools, not the workflow runtime**, which offers no pre-start hook. Every tool a workflow calls first (`plan`, `state`, `up`, `resume`, `briefing`, `commit`) refuses when `harness/` is at another commit, naming both. The effect is a workflow that stops at launch. `cleanup` and `close` never refuse: a drifted workspace must still be able to shut down and hand over.
- **A drifted checkout is repaired by moving `harness/` back to the pin, not by moving the pin forward.** Recovery is `bin/pin <client> $(cat product/harness.pin)`. Resuming a crashed run on a newer engine than the one that started it silently changes the rules mid-run, which is the failure the pin exists to prevent.
- `/harness-plan` produces a plan with only machine-runnable criteria on a sample legacy repo.
- `/harness-build` runs unattended to completion (or to BLOCKED items) on that sample, commits pass the hygiene tests, ports are released after.
- `/harness-retro` edits harness files without adding history sections, pushes, and handles a forced push rejection by pulling and retrying.
- A run killed mid-sub-task resumes with `harness/bin/resume` and reaches the same end state as an uninterrupted one.
- `/harness-plan` emits `spec-gaps.md`, and a deliberately incomplete spec produces gaps rather than silent assumptions.
- Token and duration totals appear in the end report and in `product/cost-log.md`.
- A secret in a stack's boot output does not appear in any transcript.
- A stack that never passes its health check fails the run at the environment step, not three attempts later.
- A monorepo client produces one worktree and one branch for a feature spanning two stacks.
- `harness/bin/rollback` returns the engine to the previous retro tag with a revert, and the rolled-back intent lands in `OPEN_QUESTIONS.md`.
- A `service` feature runs end to end with no design input.
- A zone whose safety net cannot be made to go red fails phase 3.
- An agent attempting to edit a file under `product/tests/` during build is refused.
- A regression in the client's own suite is caught by the baseline diff at QA.
- Plan-ready, run-finished and needs-answer messages arrive on Telegram; nothing else does.
- A workflow refuses to start when `harness/` does not match `product/harness.pin`.
- A resume whose recorded port is held by a foreign process reallocates and continues.
- A worker returning `RESTART:` gets a restarted stack and its original briefing, with no attempt spent.
- A push to any ref other than the feature branch is refused by the hook, in bypass permission mode. Git hooks are per repository, not per worktree: one `core.hooksPath` per client repo covers every worktree of it, and the hook reads its feature from the worktree path it was invoked from.
- A retro tag never reaches the harness remote before its branch does.
- QA stops at `max_fixes` and delivers with the remaining failures named in the report.
- An edited `plan.md` changes what the build does; a malformed one fails at launch with the offending line quoted.
- A retro commit naming a client, repo or service is refused by `hygiene.sh`.
- Phase 5 runs `journey.md`, and a feature with no journey fails planning.
- `hygiene.sh` passes on a repo whose `CLAUDE.md` states the hygiene rules in plain words.
- A `depends_on` naming something that is not a declared stack fails validation.
- A resumed run verifies its sub-tasks against criteria held in `state.json`, with `plan.md` untouched.
- `harness/tests/hygiene.sh` green on the harness's own files and on the product layer.
- Total harness instruction text under 40,000 characters.
- Harness test suite green.

### 19.1 Open, on purpose

Two questions have now been raised by two separate retros and are recorded rather than answered, because inventing a mechanism for a failure nobody has hit yet is how v1 grew four generations of correctives:

- **The reviewer's edits go stale the same way a worker's do.** A review pass that reads a file, thinks, and writes finds the file moved under it after a restart or a concurrent fix, and nothing detects it.
- **The reviewer has no restart channel.** `RESTART:` is a worker result. A reviewer meeting a dead stack has no way to say so.

Give the reviewer the worker's restart channel, since that costs nothing and the mechanism already exists. Leave the staleness open until a real run produces one, then fix the case that actually occurred.

## 20. Lessons from v1

The previous harness works but fails on three axes: it interrupts too often, its instruction corpus drifted from system description into change history, and that corpus grew past what any run can afford to load. Each rule below fixes something measured in that repo, not something imagined.

### 20.1 The hygiene rule needs enforcement, not a statement

v1 already carried the rule. `loop-economy.md` rule 3 says history belongs in the journal and the commit message, never in the files. The repo still holds 201 archaeology markers across its markdown, 236 ticket references in one backlog file, and lines like `Before WF-78 the skeletons lived in stacks/` sitting in the root context file. The rule applied to product code and never to the harness itself.

So it is a test, not an instruction:

- `harness/tests/hygiene.sh` greps harness-owned prose for: a date, a ticket id, and the words `superseded`, `retired`, `deprecated`, `used to`, `previously`, `no longer`, `before <id>`, `as of`.
- Any hit fails. The retro cannot commit a failing tree.
- The check is a grep, never an agent judgement. An agent asked to assess its own writing will always find a reason the sentence is load-bearing.

**Scope.** A word list that cannot be written down anywhere makes its own rule unstateable, and the first build hit this: the file defining the rule had to avoid its own vocabulary.

- The check covers prose files: `CLAUDE.md`, agent files, skills, `conventions.md`, `code-map/`, `OPEN_QUESTIONS.md`.
- It does not cover file paths, code, schemas, fixtures or machine state. A path is not prose.
- Exactly one file is exempt: `hygiene.sh` itself, which has to name what it forbids. The exemption is a hardcoded path, not a marker other files can adopt.
- Every other file, `CLAUDE.md` included, states the rule and points at the script for the list. One location per rule (20.2) applies to the list itself: a copy in prose is a copy that drifts.
- Machine state carries durations, never timestamps, so `state.json` has nothing for the date grep to find. This is a real constraint on section 8, not a coincidence.

**The spec file is `SPEC.md`.** A version number in a filename is the same accretion in a different place, and every file referencing it inherits it.

### 20.2 Edit the rule, never stack a new one on top

v1's `autonomy.md` is 17,000 characters holding four generations of patches, one superseding another in place, each added the day a run stopped somewhere unexpected. The file stopped describing the system and started narrating its own repair history.

- One subject, one rule, one location. A retro that wants to change behaviour rewrites the existing rule.
- A retro is not allowed to add a rule on a subject that already has one. If the existing rule is wrong, replace its text.
- Growth is a signal: if a file grows across three consecutive retros without another shrinking, that goes to `OPEN_QUESTIONS.md` as a design problem, not a wording problem.

### 20.3 Never generate a second copy of the corpus

v1 concatenates `capabilities/*.md` into an 81,000-character `skills-tools.md`. Both copies are in the repo, both are readable, and drift between them is invisible. Total instruction corpus across skills, conventions and context files is roughly 370,000 characters.

- No generated aggregate file. If several agents need the same block, they load the same file.
- Budget: total harness-owned instruction text under 40,000 characters. Over that, the retro files it as a problem instead of writing more.

### 20.4 Autonomy is mechanical here, so drop the doctrine

v1 spent its longest convention file on when to ask. Rules on grounding rungs, closed registers, pinned gates, report-versus-question tables. All of it was necessary because the loop could always stop.

In v2 it cannot. `/harness-build` runs as a dynamic workflow, which accepts no user input mid-run, so the only human checkpoint is where the pipeline puts it. What replaces the doctrine:

- Any decision the plan does not answer is taken, executed, and recorded in `decisions.md` with its source.
- A worker that truly cannot proceed marks the subtask BLOCKED and the run moves to the next one. Blocked is computed from the plan, never declared by an agent.
- Ali reads decisions after the run. Wrong calls become plan-phase criteria next time, not new rules about asking.

### 20.5 Carry over from v1

These worked. They move to v2 as written, minus the history around them.

- **The ask format.** Lettered options, one line each, the recommendation marked, everything technical below a `Detail:` line, plain words above it, and always state what is still running. This already matches section 13; v1 got the format right and the trigger wrong.
- **A report is never a question.** A progress report ends with what happened. The run continues by default.
- **Parking beats halting.** One blocked subtask parks; every other runnable subtask keeps going. Matches the failure policy in section 5.
- **An answered ask reopens what it parked.** Parking without a way back is just a slower halt: the sub-task stops, its dependents are skipped, and the work leaves the run permanently. `bin/answer <slug> <st-id> <letter>` writes the choice into state, sets the parked sub-task to pending, and resets the sub-tasks skipped on its account. The next `/harness-build` picks them up with the answer in the briefing. Ali answers from the report, after the run, which is the whole point of not waiting for him during it.
- **Frozen oracle.** The implementer may not edit the tests written before it. A test that looks wrong is a stop, never an edit. This is what makes the regression net in phase 3 mean anything.
- **Cite the ground.** Every recorded decision names where it came from: the spec, the design, an existing pattern in the client code, or the agent's own judgement with a stated reason. Judgement is allowed; presenting judgement as spec is not.
- **Two reduction-pass rules with real evidence behind them:** delete a superseded path in the same subtask rather than leaving it additively, and grep the module's existing helpers before writing a new one. v1 recorded the same index-resolution helper written three times in one module across three reopened loops.