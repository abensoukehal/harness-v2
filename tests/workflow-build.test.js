// The build script decides two things in JavaScript that no Python tool sees. Each is one expression, so each is
// lifted out of the script and run here against the state that must and must not trigger it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const build = readFileSync(fileURLToPath(new URL("../claude/workflows/harness-build.js", import.meta.url)), "utf8");

function condition(marker, start, args) {
  const line = build.split("\n").find((l) => l.includes(marker));
  assert.ok(line, `no line in harness-build.js holds ${marker}`);
  const expr = line.slice(line.indexOf(start), line.indexOf(" ? ["));
  return new Function(...args, `return Boolean(${expr})`);
}

test("the over line budget friction is recorded only for a sub-task actually over its budget", () => {
  const fires = condition("over line budget", "review && review.justification", ["review", "lines_added", "byId", "id"]);
  const plan = { "st-01": { line_budget: 60 }, "st-02": { line_budget: 24 }, "st-03": { line_budget: 120 } };
  const byId = () => plan;
  const review = { justification: "the reduction pass left the helper in place" };
  for (const [id, lines] of [["st-01", 24], ["st-02", 24], ["st-03", 119]]) {
    assert.equal(fires(review, lines, byId, id), false, `${id} came in under its budget with ${lines} lines`);
  }
  assert.equal(fires(review, 61, byId, "st-01"), true, "61 lines against a budget of 60 is an overrun");
  assert.equal(fires({}, 61, byId, "st-01"), false, "an overrun the reviewer did not justify is the reviewer's problem, not a friction");
});
