import { test } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { load, validate, validateFile } from "../lib/validate.js";

const fixture = (p) => fileURLToPath(new URL(`fixtures/${p}`, import.meta.url));
const cli = fileURLToPath(new URL("../bin/validate", import.meta.url));
const fixtures = ["two-stack/client.config.yaml", "monorepo/client.config.yaml", "two-stack/state.json", "monorepo/state.json"];

test("fixtures are valid", () => {
  for (const f of fixtures) assert.deepEqual(validateFile(fixture(f)), { ok: true, pass: "cross-field", errors: [] }, f);
});

function rejects(schema, file, cases) {
  const base = load(fixture(file));
  for (const [name, mutate, pathRe] of cases) {
    test(`${schema} rejects ${name}`, () => {
      const data = structuredClone(base);
      mutate(data);
      const r = validate(data, schema);
      assert.equal(r.ok, false);
      assert.ok(r.errors.some((e) => pathRe.test(e.path)), `no error at ${pathRe}; got ${JSON.stringify(r.errors)}`);
    });
  }
}

rejects("config", "two-stack/client.config.yaml", [
  ["missing client", (c) => delete c.client, /^\/client$/],
  ["client with uppercase", (c) => (c.client = "Acme"), /^\/client$/],
  ["unknown top-level key", (c) => (c.extra = 1), /^\/extra$/],
  ["no stacks", (c) => (c.stacks = {}), /^\/stacks$/],
  ["stack name unusable as PORT_ var", (c) => (c.stacks["Front-End"] = c.stacks.frontend), /^\/stacks\/Front-End$/],
  ["stack without repo", (c) => delete c.stacks.frontend.repo, /^\/stacks\/frontend\/repo$/],
  ["stack without health", (c) => delete c.stacks.frontend.health, /^\/stacks\/frontend\/health$/],
  ["stack without health_timeout_s", (c) => delete c.stacks.backend.health_timeout_s, /^\/stacks\/backend\/health_timeout_s$/],
  ["repo null with a path", (c) => (c.stacks.frontend.repo = null), /^\/stacks\/frontend\/path$/],
  ["path null with a repo", (c) => (c.stacks.frontend.path = null), /^\/stacks\/frontend\/path$/],
  ["health tcp next to log", (c) => (c.stacks.db.health = { tcp: "${PORT_DB}", log: "x" }), /^\/stacks\/db\/health$/],
  ["depends_on an undeclared stack", (c) => (c.stacks.backend.depends_on = ["cache"]), /^\/stacks\/backend\/depends_on\/0$/],
  ["path outside its repo", (c) => (c.stacks.frontend.path = "repos/other"), /^\/stacks\/frontend\/path$/],
  ["path not under repos/", (c) => (c.stacks.frontend.path = "frontend"), /^\/stacks\/frontend\/path$/],
  ["commands without dev", (c) => delete c.stacks.backend.commands.dev, /^\/stacks\/backend\/commands\/dev$/],
  ["unknown command", (c) => (c.stacks.backend.commands.deploy = "x"), /^\/stacks\/backend\/commands\/deploy$/],
  ["empty command", (c) => (c.stacks.backend.commands.test = ""), /^\/stacks\/backend\/commands\/test$/],
  ["env_file with a path", (c) => (c.stacks.frontend.env_file = "../secrets/.env"), /^\/stacks\/frontend\/env_file$/],
  ["dev_url without scheme", (c) => (c.stacks.frontend.dev_url = "localhost:3000"), /^\/stacks\/frontend\/dev_url$/],
  ["depends_on unknown stack", (c) => (c.stacks.frontend.depends_on = ["mobile"]), /^\/stacks\/frontend\/depends_on\/0$/],
  ["self dependency", (c) => (c.stacks.backend.depends_on = ["backend"]), /^\/stacks\/backend\/depends_on\/0$/],
  ["dependency cycle", (c) => (c.stacks.backend.depends_on = ["frontend"]), /^\/stacks$/],
  ["health with both log and http", (c) => (c.stacks.frontend.health = { log: "x", http: "y", expect_status: 200 }), /^\/stacks\/frontend\/health$/],
  ["health empty", (c) => (c.stacks.frontend.health = {}), /^\/stacks\/frontend\/health$/],
  ["health http without expect_status", (c) => delete c.stacks.backend.health.expect_status, /^\/stacks\/backend\/health\/expect_status$/],
  ["expect_status 999", (c) => (c.stacks.backend.health.expect_status = 999), /^\/stacks\/backend\/health\/expect_status$/],
  ["health_timeout_s 0", (c) => (c.stacks.backend.health_timeout_s = 0), /^\/stacks\/backend\/health_timeout_s$/],
  ["PORT ref to a missing stack", (c) => (c.stacks.frontend.commands.dev = "pnpm dev --port ${PORT_MOBILE}"), /^\/stacks\/frontend$/],
  ["delivery mode rebase", (c) => (c.delivery.mode = "rebase"), /^\/delivery\/mode$/],
  ["delivery without commit_author", (c) => delete c.delivery.commit_author, /^\/delivery\/commit_author$/],
  ["commit_author bad email", (c) => (c.delivery.commit_author.email = "not-an-email"), /^\/delivery\/commit_author\/email$/],
  ["git identity_hygiene lax", (c) => (c.git.identity_hygiene = "lax"), /^\/git\/identity_hygiene$/],
  ["inline telegram chat id", (c) => (c.notify.telegram = { chat_id: 12345 }), /^\/notify\/telegram\/chat_id/],
  ["unknown notify event", (c) => c.notify.events.push("deploy_done"), /^\/notify\/events\/3$/],
  ["duplicate notify event", (c) => c.notify.events.push("plan_ready"), /^\/notify\/events$/],
  ["client_tests key not a stack", (c) => (c.client_tests.mobile = "x"), /^\/client_tests\/mobile$/],
  ["test_runner key not a stack", (c) => (c.test_runner.mobile = "x"), /^\/test_runner\/mobile$/],
  ["missing test_runner", (c) => delete c.test_runner, /^\/test_runner$/],
  ["tokens_per_feature 0", (c) => (c.budget.tokens_per_feature = 0), /^\/budget\/tokens_per_feature$/],
  ["max_fixes negative", (c) => (c.qa.max_fixes = -1), /^\/qa\/max_fixes$/],
  ["viewport malformed", (c) => (c.visual.viewport = "1440"), /^\/visual\/viewport$/],
  ["threshold_pct over 100", (c) => (c.visual.threshold_pct = 150), /^\/visual\/threshold_pct$/],
  ["visual without max_attempts", (c) => delete c.visual.max_attempts, /^\/visual\/max_attempts$/],
  ["max_parallel_features 0", (c) => (c.max_parallel_features = 0), /^\/max_parallel_features$/],
]);

rejects("state", "two-stack/state.json", [
  ["missing harness_commit", (s) => delete s.harness_commit, /^\/harness_commit$/],
  ["harness_commit not a sha", (s) => (s.harness_commit = "main"), /^\/harness_commit$/],
  ["missing kind", (s) => delete s.kind, /^\/kind$/],
  ["kind unknown", (s) => (s.kind = "fullstack"), /^\/kind$/],
  ["phase unknown", (s) => (s.phase = "building"), /^\/phase$/],
  ["unknown top-level key", (s) => (s.started_at = "now"), /^\/started_at$/],
  ["port below 1024", (s) => (s.ports.frontend = 80), /^\/ports\/frontend$/],
  ["worktree outside .worktrees", (s) => (s.worktrees.frontend = "repos/frontend"), /^\/worktrees\/frontend$/],
  ["worktree for another feature", (s) => (s.worktrees.frontend = ".worktrees/other/frontend"), /^\/worktrees\/frontend$/],
  ["status unknown", (s) => (s.subtasks[0].status = "finished"), /^\/subtasks\/0\/status$/],
  ["done without commit", (s) => delete s.subtasks[0].commit, /^\/subtasks\/0\/commit$/],
  ["done without cost", (s) => delete s.subtasks[0].cost, /^\/subtasks\/0\/cost$/],
  ["cost without lines_added", (s) => delete s.subtasks[0].cost.lines_added, /^\/subtasks\/0\/cost\/lines_added$/],
  ["negative duration", (s) => (s.subtasks[0].cost.duration_s = -1), /^\/subtasks\/0\/cost\/duration_s$/],
  ["cost flattened onto the sub-task", (s) => (s.subtasks[0].tokens_in = 1), /^\/subtasks\/0\/tokens_in$/],
  ["missing interruptions", (s) => delete s.subtasks[0].interruptions, /^\/subtasks\/0\/interruptions$/],
  ["interruptions 4", (s) => (s.subtasks[1].interruptions = 4), /^\/subtasks\/1\/interruptions$/],
  ["missing worktree", (s) => delete s.subtasks[0].worktree, /^\/subtasks\/0\/worktree$/],
  ["worktree of another feature", (s) => (s.subtasks[0].worktree = ".worktrees/other/backend"), /^\/subtasks\/0\/worktree$/],
  ["criteria as a pointer to plan.md", (s) => (s.subtasks[2].exit_criteria = "plan.md#st-03"), /^\/subtasks\/2\/exit_criteria$/],
  ["criterion item as a pointer", (s) => (s.subtasks[2].exit_criteria = [{ ref: "plan.md#st-03" }]), /^\/subtasks\/2\/exit_criteria\/0\/kind$/],
  ["no criteria at all", (s) => (s.subtasks[2].exit_criteria = []), /^\/subtasks\/2\/exit_criteria$/],
  ["baseline under the old key", (s) => { s.baseline = s.client_test_baseline; delete s.client_test_baseline; }, /^\/baseline$/],
  ["blocked without reason", (s) => delete s.subtasks[1].reason, /^\/subtasks\/1\/reason$/],
  ["attempts 4", (s) => (s.subtasks[1].attempts = 4), /^\/subtasks\/1\/attempts$/],
  ["last_error too long", (s) => (s.subtasks[1].last_error = "x".repeat(2001)), /^\/subtasks\/1\/last_error$/],
  ["duplicate sub-task id", (s) => (s.subtasks[2].id = "st-01"), /^\/subtasks\/2\/id$/],
  ["sub-task id malformed", (s) => (s.subtasks[2].id = "task-3"), /^\/subtasks\/2\/id$/],
  ["depends_on unknown sub-task", (s) => (s.subtasks[2].depends_on = ["st-09"]), /^\/subtasks\/2\/depends_on\/0$/],
  ["unknown sub-task key", (s) => (s.subtasks[2].notes = "x"), /^\/subtasks\/2\/notes$/],
  ["criterion kind manual", (s) => (s.subtasks[2].exit_criteria[0].kind = "manual"), /^\/subtasks\/2\/exit_criteria\/0\/kind$/],
  ["http criterion without expect_status", (s) => delete s.subtasks[0].exit_criteria[1].expect_status, /^\/subtasks\/0\/exit_criteria\/1\/expect_status$/],
  ["log criterion without present", (s) => delete s.subtasks[2].exit_criteria[1].present, /^\/subtasks\/2\/exit_criteria\/1\/present$/],
  ["accepted gap without region", (s) => s.accepted_gaps.push({ subtask: "st-02", divergence_pct: 3.1 }), /^\/accepted_gaps\/0\/region$/],
  ["decisions not strings", (s) => (s.decisions = [{}]), /^\/decisions\/0$/],
]);

rejects("state", "monorepo/state.json", [
  ["skipped without reason", (s) => delete s.subtasks[1].reason, /^\/subtasks\/1\/reason$/],
  ["examples floor 1", (s) => (s.subtasks[2].exit_criteria[1].floor = 1), /^\/subtasks\/2\/exit_criteria\/1\/floor$/],
  ["examples without set", (s) => delete s.subtasks[2].exit_criteria[1].set, /^\/subtasks\/2\/exit_criteria\/1\/set$/],
]);

function run(...args) {
  try {
    return { status: 0, stderr: execFileSync(cli, args, { stdio: "pipe" }).toString() };
  } catch (e) {
    return { status: e.status, stderr: e.stderr.toString() };
  }
}

test("state schema names no timestamp field", () => {
  const schema = JSON.parse(readFileSync(new URL("../schemas/state.schema.json", import.meta.url), "utf8"));
  const names = [];
  const walk = (node) => {
    if (!node || typeof node !== "object") return;
    for (const [k, v] of Object.entries(node)) {
      if (k === "properties") names.push(...Object.keys(v));
      walk(v);
    }
  };
  walk(schema);
  const suspects = names.filter((n) => /(_at$|^created|^updated|time$|timestamp|date)/i.test(n));
  assert.deepEqual(suspects, []);
});

test("cli: valid file exits 0 silently", () => {
  assert.deepEqual(run(fixture("monorepo/state.json")), { status: 0, stderr: "" });
});

test("cli: invalid file exits 1 and names the offending path", () => {
  const dir = mkdtempSync(join(tmpdir(), "harness-validate-"));
  const file = join(dir, "client.config.yaml");
  writeFileSync(file, readFileSync(fixture("two-stack/client.config.yaml"), "utf8").replace("    repo: frontend\n", ""));
  const { status, stderr } = run(file);
  assert.equal(status, 1);
  assert.match(stderr, /client\.config\.yaml:\/stacks\/frontend\/repo: missing required key "repo"/);
  assert.match(stderr, /schema error\(s\); cross-field checks run once the schema pass is clean/);
});

test("cli: unknown file name without --schema exits 2", () => {
  const { status, stderr } = run(fixture("two-stack/state.json").replace("state.json", "nope.json"));
  assert.equal(status, 2);
  assert.match(stderr, /--schema/);
});

test("cli: --schema overrides the file name", () => {
  const dir = mkdtempSync(join(tmpdir(), "harness-validate-"));
  const file = join(dir, "anything.json");
  writeFileSync(file, readFileSync(fixture("monorepo/state.json")));
  assert.equal(run(file, "--schema", "state").status, 0);
  assert.equal(run(file, "--schema", "config").status, 1);
});

test("cli: malformed yaml exits 2 with a line number", () => {
  const dir = mkdtempSync(join(tmpdir(), "harness-validate-"));
  const file = join(dir, "client.config.yaml");
  writeFileSync(file, "client: x\nstacks:\n  frontend: [\n");
  const { status, stderr } = run(file);
  assert.equal(status, 2);
  assert.match(stderr, /line \d+/);
});
