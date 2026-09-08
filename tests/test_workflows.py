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

    def test_pure_orchestration(self):
        for p in SCRIPTS:
            text = p.read_text()
            for pattern in BANNED:
                self.assertIsNone(re.search(pattern, text, re.M), "%s uses %s" % (p.name, pattern))
            self.assertIn("harness/", text)
