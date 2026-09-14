import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

SCRIPTS = sorted((ROOT / "claude" / "workflows").glob("*.js"))


def decisions_block(path):
    """The pure-function block each script lifts its branches into, between its two markers."""
    parts = path.read_text().split("/* decisions:start */")
    assert len(parts) == 2, "%s has no decisions block" % path.name
    return parts[1].split("/* decisions:end */")[0]


def literal_keys(text, brace):
    """The top-level keys of the object literal whose opening brace is at `brace`."""
    keys, depth, i = [], 0, brace
    while i < len(text):
        c = text[i]
        if c in "{([":
            depth += 1
        elif c in "})]":
            depth -= 1
            if not depth:
                return keys
        elif c in "'\"`":
            i += 1
            while i < len(text) and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif depth == 1:
            name = re.match(r"([A-Za-z_$][\w$]*)\s*:", text[i:])
            if name:
                keys.append(name.group(1))
                i += name.end() - 1
        i += 1
    raise AssertionError("unterminated object literal at %d" % brace)


def patch_keys(text):
    """Every top-level key a script writes into state.json, read off the patch literals themselves."""
    return {k for m in re.finditer(r"(?:setState\('[a-z-]+', |JSON\.stringify\()\{", text)
            for k in literal_keys(text, m.end() - 1)}


def unknown(keys, properties):
    return sorted(k for k in keys if k not in properties)


BANNED = [r"Date\.now", r"Math\.random", r"new Date\(\)", r"\brequire\(", r"^\s*import\s", r"\bfs\.", r"process\."]


class Workflows(unittest.TestCase):
    def test_three_scripts_parse(self):
        self.assertEqual([p.stem for p in SCRIPTS], ["harness-build", "harness-plan", "harness-retro"])
        # The runtime wraps the body in an async function, so top-level return and await are legal there.
        with tempfile.TemporaryDirectory() as d:
            for p in SCRIPTS:
                meta, body = p.read_text().split("\n}\n", 1)
                wrapped = Path(d) / (p.stem + ".mjs")
                wrapped.write_text(meta.replace("export const", "const") + "\n}\n;(async () => {\n" + body + "\n})()\n")
                done = subprocess.run(["node", "--check", str(wrapped)], capture_output=True, text=True)
                self.assertEqual(done.returncode, 0, "%s: %s" % (p.name, done.stderr))

    def test_meta_and_phases(self):
        for p in SCRIPTS:
            text = p.read_text()
            self.assertTrue(text.startswith("export const meta = {"), p.name)
            self.assertIn("name: '%s'" % p.stem, text)
            declared = set(re.findall(r"title: '([^']+)'", text.split("\n}\n", 1)[0]))
            used = set(re.findall(r"phase\('([^']+)'\)", text)) | set(re.findall(r"\bphase: '([A-Z][^']*)'", text))
            self.assertEqual(used - declared, set(), p.name)

    def test_build_is_mechanical_where_it_matters(self):
        text = (ROOT / "claude/workflows/harness-build.js").read_text()
        self.assertLess(text.index("${T('net')} check"), text.index("${T(resuming ? 'resume' : 'up')}"))
        self.assertLess(text.index("${T('baseline')}"), text.index("agentType: 'test-writer'"), "the baseline is a tool, run before the test-writer")
        self.assertNotIn("baseline:", text.split("const NET")[1].split("}")[0], "the test-writer does not report the baseline")
        self.assertLess(text.index("${T('net')} freeze"), text.index("${T('next')}"))
        self.assertLess(text.index("${T('cost')}"), text.index("${T('report')}"), "input tokens land in state before the report reads them")
        self.assertNotIn("budget.spent()", text, "output deltas are not the cost")
        self.assertLess(text.index("${T('report')}"), text.index("${T('notify')} ${slug} run_finished"))
        for name in ["harness-plan", "harness-retro"]:
            self.assertIn("${T('cost')}", (ROOT / "claude/workflows" / (name + ".js")).read_text(), name)
        self.assertIn("--reseed", text)
        self.assertNotIn("communicate skill", text, "the report is a tool, not an agent")
        retro = (ROOT / "claude/workflows/harness-retro.js").read_text()
        self.assertLess(retro.index("${T('retro-tree')}"), retro.index("agentType: 'retro'"), "the retro gets its own clone before it edits")
        self.assertIn("harness_at_pin", retro)
        skill = (ROOT / "claude/skills/retro/SKILL.md").read_text()
        self.assertNotIn("git -C harness pull", skill)
        self.assertNotIn("harness/bin/tag-push", skill)
        plan = (ROOT / "claude/workflows/harness-plan.js").read_text()
        self.assertIn("${T('notify')} ${slug} plan_ready", plan)
        self.assertLess(plan.index("${T('review')}"), plan.index("${T('notify')} ${slug} plan_ready"), "the review renders the message the push sends")
        self.assertNotIn("plan_message", plan, "no agent writes the plan-ready message (13.3)")
        self.assertNotIn("message: planning.message", plan)


    def test_every_agent_spawn_takes_its_model_and_effort_from_the_config(self):
        """6.3: the pair is config, static per workspace, and no script names a model."""
        for path in SCRIPTS:
            text = path.read_text()
            for opts in re.findall(r"\{[^{}]*\bagentType:[^{}]*\}", text):
                role = re.search(r"agentType: '([a-z-]+)'", opts).group(1)
                if "effort: 'low'" in opts:
                    continue  # the spawns that run before the config can be read; the line below checks their marker
                self.assertIn("...A('%s')" % role, opts, "%s: %s spawns without its configured pair" % (path.name, role))
            # The io steps read theirs too. Only the spawns that run before the config can be read spell the default out.
            for line in [l for l in text.splitlines() if "effort: 'low'" in l]:
                self.assertTrue('"$HARNESS_WORKSPACE"' in line or "the io default, spelled out once" in line,
                                "%s: %s" % (path.name, line.strip()))
            self.assertNotRegex(text, r"model: '", "%s names a model; models live in client.config.yaml (6.3)" % path.name)
        self.assertIn("${T('agents')}", (ROOT / "claude/workflows/harness-plan.js").read_text())
        self.assertIn("${T('agents')}", (ROOT / "claude/workflows/harness-retro.js").read_text())
        self.assertIn("cfg.agents", (ROOT / "claude/workflows/harness-build.js").read_text())

    def test_workspace_root_is_passed_never_resolved(self):
        for p in SCRIPTS:
            text = p.read_text()
            self.assertIn('"$HARNESS_WORKSPACE"', text, p.name)
            self.assertIn("args.workspace", text, p.name)
            code = "\n".join(l for l in text.splitlines() if not l.strip().startswith("//") and "workspace root unknown" not in l)
            self.assertEqual(code.count("harness/bin"), 1, "%s: every tool call goes through the absolute BIN" % p.name)
            self.assertNotIn("`product/", code, p.name)
            self.assertNotIn("workspace root. ", code, p.name)

    def test_a_runtime_refusal_is_retried_once_then_a_friction(self):
        """The retry policy is one lifted function; workflow-decisions.test.js drives both of its refusals."""
        for p in SCRIPTS:
            text = p.read_text()
            self.assertIn("const retrying = async (call, label, note) => {", decisions_block(p), p.name)
            self.assertIn("const r = await retrying(() => agent(prompt, opts), opts.label, log)", text, p.name)
            self.assertIn("refused to start it twice: ${refusal} · runtime", text, "%s: the friction carries the runtime's reason" % p.name)
            after = text.split("const spawn = async (prompt, opts)", 1)[1]
            self.assertNotIn("await agent(", after, "%s: every spawn after the helper goes through it" % p.name)
            self.assertGreaterEqual(after.count("await spawn("), 2, p.name)
        build = (ROOT / "claude/workflows/harness-build.js").read_text()
        self.assertIn("outcome = { status: 'skipped', reason: 'runtime' }", build)
        self.assertIn("attempts: attemptsOf(worker, outcome, byId()[id].attempts, spent)", build, "a refusal spends no attempt")

    def test_commands_with_no_agent_between_them_share_one_spawn(self):
        """An io spawn carries ~52k of context whatever it is asked (6.2), so the count is the only lever there is."""
        build = (ROOT / "claude/workflows/harness-build.js").read_text()
        self.assertNotIn("const io = (", build, "no single-command io helper survives the batch")
        batches = []
        for start in [m.end() for m in re.finditer(r"runAll\(", build)]:
            depth, i = 0, start
            while i < len(build):
                if build[i] in "([{":
                    depth += 1
                elif build[i] in ")]}":
                    if depth == 0:
                        break
                    depth -= 1
                i += 1
            call = build[start:i]
            batches.append(re.findall(r"(?:step|setState|getState)\('([a-z-]+)'|\b(brief)\(", call))
        named = [[a or "briefing" for a, b in group] for group in batches]
        for want in [["net-check", "plan-in", "environment", "baseline", "state"],  # the launch, either branch
                     ["net-freeze", "phase"],
                     ["running", "briefing"],
                     ["restart", "briefing"],
                     ["state", "phase"],                                            # the build read and the QA phase
                     ["state", "phase", "push"],                                    # delivery, the push allowed to fail
                     ["phase", "cost", "report", "notify"]]:
            self.assertIn(want, named, "these commands have no agent between them and must share one spawn")
        for role in ["io"]:
            for p in SCRIPTS:
                self.assertIn("agentType: '%s'" % role, p.read_text(), "%s: the io steps run on the restricted agent" % p.name)

    def test_every_lifted_decision_is_driven_by_a_test(self):
        """14.7: a branch asserted only as text in the script passes whether or not any input reaches it."""
        driven = (ROOT / "tests/workflow-decisions.test.js").read_text()
        for p in SCRIPTS:
            block = decisions_block(p)
            names = re.findall(r"^const (\w+) =", block, re.M)
            self.assertGreaterEqual(len(names), 5, p.name)
            for name in names:
                self.assertRegex(driven, r"\b%s\(" % name, "%s: %s is lifted but nothing calls it" % (p.name, name))
            body = p.read_text().split("/* decisions:end */", 1)[1]
            for name in names:
                self.assertRegex(body, r"\b%s\b" % name, "%s: %s is lifted and then unused" % (p.name, name))

    def test_nothing_landed_skips_qa_and_delivery(self):
        build = (ROOT / "claude/workflows/harness-build.js").read_text()
        self.assertIn("${T('deliver')}", build, "the push is a tool that can refuse, not a git line in a prompt")
        self.assertNotIn("push origin", build)
        self.assertIn("!landed ? 'nothing landed'", build)
        self.assertNotIn("result_schema", build, "the worker schema is inline, in the dialect agent() accepts")
        self.assertNotIn("$schema", build)
        gate = build.index("if (!landedCount(state))")
        self.assertLess(gate, build.index("phase('QA')"))
        self.assertLess(gate, build.index("setState('undelivered'"))
        self.assertLess(build.index("QA and delivery skipped"), build.index("phase('QA')"))

    def test_every_command_in_an_agent_prompt_carries_its_directory(self):
        """The cwd rule is for agents too (2.2): a command in a prompt names where it runs, quoted or batched."""
        rooted = ("${WS}", "${TREE_DIR}", "${T(", "${FEATURE}")
        for p in SCRIPTS:
            text = p.read_text()
            for command in re.findall(r"\\`([^`]+)\\`", text):
                self.assertTrue(any(r in command for r in rooted), "%s: %r resolves from the working directory" % (p.name, command))
            # A batched command is the second argument of step(); it is a command too.
            for command in re.findall(r"\bstep\('[^']+', `([^`]*)`", text):
                self.assertTrue(any(r in command for r in rooted), "%s: %r resolves from the working directory" % (p.name, command))

    def test_comparable_reaches_the_qa_prompt(self):
        build = (ROOT / "claude/workflows/harness-build.js").read_text()
        qa = build[build.index("Global QA per your Method") - 400:build.index("agentType: 'qa'")]
        self.assertIn("plan.comparable === false", qa)
        self.assertIn("capture no screen", qa)
        self.assertIn("${FEATURE}/design", qa)

    def test_pure_orchestration(self):
        for p in SCRIPTS:
            text = p.read_text()
            for pattern in BANNED:
                self.assertIsNone(re.search(pattern, text, re.M), "%s uses %s" % (p.name, pattern))
            self.assertIn("harness/", text)

    def test_every_state_key_a_script_writes_is_in_the_schema(self):
        """A key only a run reaches: renamed on one side it passes every other test and fails on additionalProperties.

        The scripts are the sole writer of some of what lands in state.json, and nothing here executes them. This
        reads the patch literals instead, so the two ends of a name are compared without a run.
        """
        props = json.loads((ROOT / "schemas/state.schema.json").read_text())["properties"]
        for p in SCRIPTS:
            text = p.read_text()
            self.assertEqual(text.count("${T('state')} update"), 1,
                             "%s: one write site, and its patches are literals patch_keys can read" % p.name)
            keys = patch_keys(text)
            self.assertTrue(keys, "%s: the write site carries no patch literal" % p.name)
            self.assertEqual(unknown(keys, props), [], "%s writes it and state.json has no such key" % p.name)
        self.assertIn("legacy_discovery", patch_keys((ROOT / "claude/workflows/harness-plan.js").read_text()),
                      "the key the plan script alone writes is the one this test exists for")
        self.assertEqual(unknown({"discovery", "phase"}, props), ["discovery"],
                         "the rule, driven by the half-rename it catches")

    def test_a_skill_that_writes_state_names_keys_the_schema_has(self):
        """The third writer of state.json is prose: visual-diff tells the agent to append an accepted gap itself.

        Renamed in the schema, the instruction still reads well and the run fails on it, the same way a script would.
        A prose write phrased any other way is invisible here, so the count below fixes what this rule sees.
        """
        props = json.loads((ROOT / "schemas/state.schema.json").read_text())["properties"]
        writes = [(m.group(2), [f.strip() for f in m.group(1).split(",")])
                  for p in sorted((ROOT / "claude").rglob("*.md"))
                  for m in re.finditer(r"append `\{([^}]*)\}` to `([a-z_]+)` in `state\.json`", p.read_text())]
        self.assertEqual(len(writes), 1, "the prose writes of state.json this rule reaches: %s" % writes)
        for key, fields in writes:
            self.assertEqual(unknown([key], props), [], "a skill appends to %s and state.json has no such key" % key)
            self.assertEqual(unknown(fields, props[key]["items"]["properties"]), [],
                             "a skill names it and an item of %s has no such field" % key)
