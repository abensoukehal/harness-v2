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
        self.assertLess(text.index("${T('net')} freeze"), text.index("${T('next')}"))
        self.assertLess(text.index("${T('report')}"), text.index("${T('notify')} ${slug} run_finished"))
        self.assertIn("--reseed", text)
        self.assertNotIn("communicate skill", text, "the report is a tool, not an agent")
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

    def test_pure_orchestration(self):
        for p in SCRIPTS:
            text = p.read_text()
            for pattern in BANNED:
                self.assertIsNone(re.search(pattern, text, re.M), "%s uses %s" % (p.name, pattern))
            self.assertIn("harness/", text)
