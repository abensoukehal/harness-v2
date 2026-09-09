import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

HYGIENE = ROOT / "tests" / "hygiene.sh"
# Banned strings are assembled at runtime; this file is code, not prose, but the samples stay out of grep's way.
DATE = "-".join(["2024", "01", "02"])
TICKET = "WF" + "-" + "78"
WORD = "previ" + "ously"
PHRASE = "no " + "longer"
BEFORE = "before " + "st-" + "03"
CLIENT = "acme" + "corp"
REPO = "billing" + "-svc"


def hygiene(harness, workspace=None):
    args = [str(HYGIENE), "--harness", str(harness)] + (["--workspace", str(workspace)] if workspace else [])
    return subprocess.run(args, capture_output=True, text=True)


class Hygiene(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.harness = Path(self.tmp.name) / "harness"
        (self.harness / "claude" / "agents").mkdir(parents=True)

    def write(self, rel, text):
        p = self.harness / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_each_rule_names_file_and_line_in_prose(self):
        self.write("CLAUDE.md", "fine\nfixed on %s\n" % DATE)
        self.write("claude/agents/b.md", "see %s for why\n" % TICKET)
        self.write("claude/skills/x/SKILL.md", "this was %s the case\n" % WORD)
        self.write("STATE.md", "we %s do this\n" % PHRASE)
        self.write("OPEN_QUESTIONS.md", "%s the layout differed\n" % BEFORE)
        self.write("templates/workspace/CLAUDE.md", "Shipped on %s 3, %s\n" % ("Mar" + "ch", "20" + "24"))
        done = hygiene(self.harness)
        self.assertEqual(done.returncode, 1)
        for rule, rel, line in [("date", "CLAUDE.md", 2), ("ticket", "claude/agents/b.md", 1), ("words", "claude/skills/x/SKILL.md", 1),
                                ("words", "STATE.md", 1), ("words", "OPEN_QUESTIONS.md", 1), ("date", "templates/workspace/CLAUDE.md", 1)]:
            self.assertIn("%s  %s:%d:" % (rule, self.harness / rel, line), done.stdout)

    def test_paths_code_schemas_fixtures_and_state_are_not_prose(self):
        self.write("CLAUDE.md", "Read only the listed files. Encode as UTF-8. Hash with SHA-256.\n")
        self.write("tests/test_x.py", "DATE = '%s'  # %s\n" % (DATE, WORD))
        self.write("schemas/x.schema.json", '{"$schema": "https://json-schema.org/draft/2020-12/schema", "note": "%s"}\n' % TICKET)
        self.write("tests/fixtures/a/state.json", '{"reason": "%s %s"}\n' % (WORD, DATE))
        self.write("lib/x.py", "# %s\n" % PHRASE)
        self.write("claude/workflows/x.js", "// %s\n" % BEFORE)
        self.write("docs/%s-notes.md" % TICKET, "a path is not prose\n")
        self.write("tests/hygiene.sh", "this copy of the script itself is skipped: %s\n" % WORD)
        done = hygiene(self.harness)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout, "")

    def test_workspace_mode_scans_client_names_and_product_layer(self):
        ws = Path(self.tmp.name) / "ws"
        (ws / "product" / "code-map").mkdir(parents=True)
        (ws / "product" / "client.config.yaml").write_text(
            "client: %s\nstacks:\n  backend:\n    repo: %s\n  web:\n    repo: shop\n  db:\n    repo: null\n" % (CLIENT, REPO))
        self.write("claude/agents/worker.md", "When %s names a table, record it.\n" % CLIENT)
        self.write("claude/skills/reduce/SKILL.md", "The %s module has helpers.\nThe shop is closed.\n" % REPO)
        self.write("claude/skills/ok/SKILL.md", "Start the backend before the web stack.\n")
        self.write("tests/fixtures/%s.yaml" % CLIENT, "client: %s\n" % CLIENT)
        (ws / "product" / "conventions.md").write_text("Errors bubble up.\nDecided on %s.\n" % DATE)
        (ws / "product" / "code-map" / "cart.md").write_text("Entry point is cart/views. %s\n" % TICKET)
        (ws / "product" / "cost-log.md").write_text("slug | tokens\nx | 1 | %s\n" % DATE)
        (ws / "product" / "features").mkdir()
        (ws / "product" / "features" / "state.json").write_text('{"note": "%s"}\n' % DATE)
        done = hygiene(self.harness, ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("client  %s:1:" % (self.harness / "claude/agents/worker.md"), done.stdout)
        self.assertIn("client  %s:1:" % (self.harness / "claude/skills/reduce/SKILL.md"), done.stdout)
        self.assertIn("client  %s:2:" % (self.harness / "claude/skills/reduce/SKILL.md"), done.stdout)
        self.assertNotIn("ok/SKILL.md", done.stdout)
        self.assertNotIn("fixtures", done.stdout)
        self.assertIn("date  %s:2:" % (ws / "product/conventions.md"), done.stdout)
        self.assertIn("ticket  %s:1:" % (ws / "product/code-map/cart.md"), done.stdout)
        self.assertNotIn("cost-log.md", done.stdout)
        self.assertNotIn("state.json", done.stdout)

    def test_a_corpus_past_the_cap_fails_the_commit(self):
        self.write("CLAUDE.md", "short and clean\n")
        self.write("claude/agents/worker.md", "a" * 39000)
        self.assertEqual(hygiene(self.harness).returncode, 0, "under the cap, nothing is said")
        self.write("claude/skills/x/SKILL.md", "b" * 1500)
        done = hygiene(self.harness)
        self.assertEqual(done.returncode, 1, "40,515 characters is past the cap")
        self.assertIn("characters, past the cap of 40000", done.stdout)

    def test_this_repo_is_clean(self):
        done = hygiene(ROOT)
        self.assertEqual(done.returncode, 0, done.stdout)
