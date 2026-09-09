// Every branch the three workflow scripts take on their own is a pure function in their decisions block. This lifts
// each block and drives, for every function, the input that trips it and the input that does not (14.7). A test that
// only asserted the throw is present in the source would pass on a condition no input can reach.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

function decisions(name) {
  const src = readFileSync(fileURLToPath(new URL(`../claude/workflows/${name}.js`, import.meta.url)), "utf8");
  const parts = src.split("/* decisions:start */");
  assert.equal(parts.length, 2, `${name}.js has no decisions block`);
  const body = parts[1].split("/* decisions:end */")[0];
  const names = [...body.matchAll(/^const (\w+) =/gm)].map((m) => m[1]);
  assert.ok(names.length, `${name}.js declares no decision`);
  // new Function gives the block no scope but its own: a decision that reached for a variable outside the block
  // throws here instead of quietly reading the script's state.
  return new Function(`${body}\nreturn { ${names.join(", ")} }`)();
}

const build = decisions("harness-build");
const plan = decisions("harness-plan");
const retro = decisions("harness-retro");

test("the slug and the workspace root are read the same way in all three scripts", () => {
  for (const [name, d] of [["build", build], ["plan", plan], ["retro", retro]]) {
    assert.equal(d.slugOf("  hello extra "), "hello", name);
    assert.equal(d.slugOf({ slug: "hello" }), "hello", name);
    assert.equal(d.slugOf(""), "", name);
    assert.equal(d.slugOf(undefined), "", name);
    assert.equal(d.workspaceRefusal("/ws/dryrun"), null, name);
    assert.match(d.workspaceRefusal("dryrun"), /HARNESS_WORKSPACE is not set/, name);
    assert.match(d.workspaceRefusal(undefined), /HARNESS_WORKSPACE is not set/, name);
  }
});

test("a runtime refusal is retried once, and only the second refusal becomes a friction", async () => {
  for (const [name, d] of [["build", build], ["plan", plan], ["retro", retro]]) {
    const said = [];
    let calls = 0;
    const once = await d.retrying(() => { calls += 1; return calls === 1 ? null : { ok: true }; }, "worker", (l) => said.push(l));
    assert.deepEqual(once, { result: { ok: true } }, `${name}: the retry is what the second call returns`);
    assert.equal(calls, 2, name);
    assert.equal(said.length, 1, `${name}: the first refusal is logged, the run goes on`);
    assert.match(said[0], /retrying once/, name);

    const twice = await d.retrying(() => null, "worker", () => {});
    assert.match(twice.friction, /^worker · the runtime refused to start it twice: returned nothing · runtime$/, name);
    assert.equal(twice.result, undefined, name);

    const threw = await d.retrying(() => { throw new Error("no tool uses"); }, "review", () => {});
    assert.match(threw.friction, /review · the runtime refused to start it twice: no tool uses · runtime/, name);

    const straight = await d.retrying(() => ({ status: "done" }), "worker", () => { throw new Error("nothing to log"); });
    assert.deepEqual(straight, { result: { status: "done" } }, name);
  }
});

test("model and effort come from the config, and only the io role has a default", () => {
  assert.deepEqual(build.agentOpts({ worker: { model: "m", effort: "high" } }, "worker"), { model: "m", effort: "high" });
  assert.deepEqual(build.agentOpts({}, "worker"), {});
  assert.deepEqual(build.agentOpts(undefined, "io"), {}, "the build reads the parsed config, which always carries the pair");
  for (const [name, d] of [["plan", plan], ["retro", retro]]) {
    assert.deepEqual(d.agentOpts({ io: { effort: "high" } }, "io"), { effort: "high" }, name);
    assert.deepEqual(d.agentOpts(undefined, "io"), { effort: "low" }, `${name}: bin/agents unreadable falls back for io only`);
    assert.deepEqual(d.agentOpts(undefined, "planner"), {}, name);
  }
});

test("a tool step is refused by its exit, and the refusal carries what the tool said", () => {
  assert.equal(build.toolRefusal("net check", { ok: true }), null);
  assert.equal(build.toolRefusal("net check", { ok: true, error: "warning" }), null);
  assert.match(build.toolRefusal("net check", { ok: false, error: "product/tests/api/test_x.py changed" }), /net check: product\/tests/);
  assert.match(build.toolRefusal("net check", { ok: false, output: "on stdout" }), /net check: on stdout/);
  assert.match(build.toolRefusal("net check", null), /the runtime returned nothing/);
  assert.equal(plan.okRefusal("state not recorded", { ok: true }), null);
  assert.match(plan.okRefusal("state not recorded", { ok: false, error: "no state" }), /state not recorded: no state/);
  assert.match(plan.okRefusal("state not recorded", null), /the runtime returned nothing/);
});

test("the build launches only on a parsed plan and an existing state", () => {
  const good = { plan_ok: true, state_exists: true };
  assert.equal(build.launchRefusal("hello", good), null);
  assert.equal(build.launchRefusal("hello", null), "launch agent returned nothing");
  assert.match(build.launchRefusal("hello", { plan_ok: false, plan_error: "line 4: unknown stack", state_exists: true }), /plan\.md refused:\nline 4/);
  assert.match(build.launchRefusal("hello", { plan_ok: true, state_exists: false }), /no state for hello: run \/harness-plan hello first/);
  assert.equal(build.stateRefusal({ state: { subtasks: [] } }), null);
  assert.equal(build.stateRefusal(null), "state could not be read");
  assert.equal(build.stateRefusal({}), "state could not be read");
});

test("state with sub-tasks resumes, and a run whose sub-tasks are all done skips the safety net", () => {
  assert.equal(build.resumes({ subtasks: [{ id: "st-01" }] }), true);
  assert.equal(build.resumes({ subtasks: [] }), false);
  assert.equal(build.netSkipped({ subtasks: [{ status: "done" }, { status: "done" }] }), true);
  assert.equal(build.netSkipped({ subtasks: [{ status: "done" }, { status: "pending" }] }), false);
  assert.equal(build.netSkipped({ subtasks: [{ status: "blocked" }] }), false);
});

test("a safety net that stays green under mutation stops the run, and names its zones", () => {
  assert.equal(build.vacuousRefusal({ zones: [{ zone: "export", mutation_red: true }] }), null);
  assert.equal(build.vacuousRefusal({ zones: [] }), null);
  const refusal = build.vacuousRefusal({ zones: [{ zone: "export", mutation_red: false }, { zone: "orders", mutation_red: true }, { zone: "summary", mutation_red: false }] });
  assert.match(refusal, /safety net is vacuous for export, summary: nothing went red under mutation/);
});

test("the build loop stops on a refused round and on nothing else", () => {
  assert.equal(build.roundRefusal({ ready: [], skipped: [], pending: 0 }), null, "no ready sub-task and none pending is the end, not a failure");
  assert.equal(build.roundRefusal({ ready: ["st-03"], skipped: [], pending: 2 }), null);
  assert.match(build.roundRefusal({ ready: [], skipped: [], pending: -1, error: "dependency cycle" }), /build loop stopped: dependency cycle/);
  assert.match(build.roundRefusal(null), /build loop stopped/);
});

test("a sub-task that cannot be briefed, restarted or reviewed lands as a blocked outcome, never as a throw", () => {
  assert.equal(build.briefingFailed({ ok: true, output: "# Briefing" }), null);
  assert.deepEqual(build.briefingFailed({ ok: false, error: "no such sub-task" }), { status: "blocked", reason: "briefing", last_error: "no such sub-task" });
  assert.equal(build.restartCapped(2, 2, "api"), null, "the second restart is still served");
  assert.deepEqual(build.restartCapped(3, 2, "api"), { status: "blocked", reason: "environment", last_error: "restart of api requested 3 times" });
  assert.equal(build.restartFailed({ ok: true }), null);
  assert.deepEqual(build.restartFailed({ ok: false, output: "health never came up" }), { status: "blocked", reason: "environment", last_error: "health never came up" });
});

test("the worker's status decides the outcome, and only done and restart carry on", () => {
  assert.equal(build.workerOutcome({ status: "done" }), null);
  assert.equal(build.workerOutcome({ status: "restart", stack: "api" }), null);
  assert.deepEqual(build.workerOutcome({ status: "needs", report: "two formats", ask: { question: "which?" } }),
    { status: "blocked", reason: "needs", last_error: "two formats", ask: { question: "which?" } });
  assert.deepEqual(build.workerOutcome({ status: "failed", last_error: "assert 3 == 2" }), { status: "blocked", reason: "criteria", last_error: "assert 3 == 2" });
  assert.deepEqual(build.workerOutcome({ status: "blocked", reason: "budget", report: "over" }), { status: "blocked", reason: "budget", last_error: "over" });
});

test("a review lands the sub-task only with a commit behind it", () => {
  const worker = { lines_added: 40 };
  assert.deepEqual(build.reviewOutcome({ status: "done", commit: "a".repeat(40), lines_added: 38 }, worker),
    { status: "done", commit: "a".repeat(40), lines_added: 38 });
  assert.deepEqual(build.reviewOutcome({ status: "done", commit: "a".repeat(40) }, worker).lines_added, 40, "the worker's count when the reviewer gives none");
  assert.deepEqual(build.reviewOutcome({ status: "done", commit: "a".repeat(40) }, {}).lines_added, 0);
  assert.deepEqual(build.reviewOutcome({ status: "done", last_error: "no commit made" }, worker),
    { status: "blocked", reason: "review", last_error: "no commit made" }, "done without a commit is not done");
  assert.equal(build.reviewOutcome({ status: "blocked", last_error: "the diff reverses st-01" }, worker).reason, "review");
});

test("a runtime refusal spends no attempt, and a worker's own count is held to three", () => {
  assert.equal(build.attemptsOf({ attempts: 2 }, { status: "skipped", reason: "runtime" }, 1), 1);
  assert.equal(build.attemptsOf({ attempts: 2 }, { status: "blocked", reason: "criteria" }, 1), 2);
  assert.equal(build.attemptsOf({ attempts: 9 }, { status: "done" }, 0), 3);
  assert.equal(build.attemptsOf({ attempts: 0 }, { status: "done" }, 0), 1);
  assert.equal(build.attemptsOf(null, { status: "done" }, 0), 1);
});

test("the over line budget friction is recorded only for a sub-task actually over its budget", () => {
  const review = { justification: "the reduction pass left the helper in place" };
  for (const [lines, budget] of [[24, 60], [24, 24], [119, 120]]) {
    assert.equal(build.overBudget(review, lines, budget), false, `${lines} lines against a budget of ${budget}`);
  }
  assert.equal(build.overBudget(review, 61, 60), true, "61 lines against a budget of 60 is an overrun");
  assert.equal(build.overBudget({}, 61, 60), false, "an overrun the reviewer did not justify is the reviewer's problem, not a friction");
  assert.equal(build.overBudget(review, 61, undefined), false, "a sub-task with no budget cannot be over it");
});

test("the run's status follows what landed, what was delivered and what stayed a gap", () => {
  const state = { subtasks: [{ status: "done" }, { status: "done" }, { status: "blocked" }] };
  assert.equal(build.landedCount(state), 2);
  assert.equal(build.landedCount({ subtasks: [] }), 0);
  assert.equal(build.runStatus(0, 3, false, 0), "nothing landed");
  assert.equal(build.runStatus(0, 3, true, 0), "nothing landed", "nothing landed wins over a delivery");
  assert.equal(build.runStatus(3, 3, false, 0), "partial");
  assert.equal(build.runStatus(2, 3, true, 0), "done with gaps");
  assert.equal(build.runStatus(3, 3, true, 1), "done with gaps");
  assert.equal(build.runStatus(3, 3, true, 0), "done");
});

test("a last error is clipped to the last ten lines and two thousand characters", () => {
  const long = Array.from({ length: 20 }, (_, i) => `line ${i}`).join("\n");
  assert.equal(build.clip(long).split("\n").length, 10);
  assert.match(build.clip(long), /^line 10\n/);
  assert.equal(build.clip("one line"), "one line");
  assert.equal(build.clip(null), "");
  assert.equal(build.clip("x".repeat(3000)).length, 2000);
});

test("planning refuses a feature with no spec, and a plan.md the parser will not take", () => {
  assert.equal(plan.specRefusal("/ws/product/features/hello", "bin/new hello", { spec_exists: true }), null);
  assert.match(plan.specRefusal("/ws/product/features/hello", "bin/new hello", { spec_exists: false }),
    /\/ws\/product\/features\/hello\/spec\.md is missing: run bin\/new hello and fill it in/);
  assert.equal(plan.parseRefusal({ ok: true, subtask_count: 3 }), null);
  assert.match(plan.parseRefusal({ ok: false, error: "line 4: unknown stack" }), /plan\.md refused: line 4: unknown stack/);
  assert.match(plan.parseRefusal(null), /plan\.md refused/);
});

test("the retro needs its own clone, and the check passes only on every count", () => {
  assert.equal(retro.treeRefusal({ ok: true, tree: "/tmp/retro/hello" }), null);
  assert.match(retro.treeRefusal({ ok: true }), /no engine clone for the retro/, "exit 0 with no path is no clone");
  assert.match(retro.treeRefusal({ ok: false, error: "the harness remote has no HEAD" }), /no engine clone for the retro: the harness remote has no HEAD/);
  assert.match(retro.treeRefusal(null), /the runtime returned nothing/);

  const green = { clean: true, tests_green: true, report_exists: true, harness_at_pin: true, tag_exists: true };
  assert.equal(retro.checkPassed(green, false), true);
  assert.equal(retro.checkPassed({ ...green, tag_exists: false }, true), true, "no tag is expected when the retro could not push");
  assert.equal(retro.checkPassed({ ...green, tag_exists: false }, false), false);
  for (const key of ["clean", "tests_green", "report_exists", "harness_at_pin"]) {
    assert.equal(retro.checkPassed({ ...green, [key]: false }, true), false, `${key} false must fail the check`);
  }
  assert.equal(retro.checkPassed(null, false), false);
});
