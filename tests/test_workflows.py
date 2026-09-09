import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

SCRIPTS = sorted((ROOT / "claude" / "workflows").glob("*.js"))
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
        for p in SCRIPTS:
            text = p.read_text()
            self.assertIn("const spawn = async (prompt, opts) => {\n  for (let i = 0; i < 2; i++) {\n    try {\n      const r = await agent(prompt, opts)", text, p.name)
            self.assertIn("· runtime`", text, p.name)
            after = text.split("const RUNTIME", 1)[1]
            self.assertNotIn("await agent(", after, "%s: every spawn after the helper goes through it" % p.name)
            self.assertGreaterEqual(after.count("await spawn("), 2, p.name)
        build = (ROOT / "claude/workflows/harness-build.js").read_text()
        self.assertIn("outcome = { status: 'skipped', reason: 'runtime' }", build)
        self.assertIn("outcome.reason === 'runtime' ? byId()[id].attempts", build, "a refusal spends no attempt")
        for p in SCRIPTS:
            self.assertIn("refused to start it twice: ${refusal} · runtime", p.read_text(), "%s: the friction carries the runtime's reason" % p.name)

    def test_nothing_landed_skips_qa_and_delivery(self):
        build = (ROOT / "claude/workflows/harness-build.js").read_text()
        self.assertIn("${T('deliver')}", build, "the push is a tool that can refuse, not a git line in a prompt")
        self.assertNotIn("push origin", build)
        self.assertIn("!landed ? 'nothing landed'", build)
        self.assertNotIn("result_schema", build, "the worker schema is inline, in the dialect agent() accepts")
        self.assertNotIn("$schema", build)
        gate = build.index("if (!state.subtasks.some((s) => s.status === 'done'))")
        self.assertLess(gate, build.index("phase('QA')"))
        self.assertLess(gate, build.index("await update({ delivered: false })"))
        self.assertLess(build.index("QA and delivery skipped"), build.index("phase('QA')"))

    def test_pure_orchestration(self):
        for p in SCRIPTS:
            text = p.read_text()
            for pattern in BANNED:
                self.assertIsNone(re.search(pattern, text, re.M), "%s uses %s" % (p.name, pattern))
            self.assertIn("harness/", text)
