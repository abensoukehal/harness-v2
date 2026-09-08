import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT

HYGIENE = ROOT / "tests" / "hygiene.sh"
# Banned strings are assembled at runtime so this file passes the check it tests.
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
        (self.harness / "claude").mkdir(parents=True)

    def write(self, rel, text):
        p = self.harness / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def test_each_rule_names_file_and_line(self):
        self.write("a.md", "fine\nfixed on %s\n" % DATE)
        self.write("b.md", "see %s for why\n" % TICKET)
        self.write("claude/c.md", "this was %s the case\n" % WORD)
        self.write("d.md", "we %s do this\n" % PHRASE)
        self.write("e.md", "%s the layout differed\n" % BEFORE)
        self.write("f.md", "Shipped on %s 3, %s\n" % ("Mar" + "ch", "20" + "24"))
        done = hygiene(self.harness)
        self.assertEqual(done.returncode, 1)
        for rule, rel, line in [("date", "a.md", 2), ("ticket", "b.md", 1), ("words", "claude/c.md", 1),
                                ("words", "d.md", 1), ("words", "e.md", 1), ("date", "f.md", 1)]:
            self.assertIn("%s  %s:%d:" % (rule, self.harness / rel, line), done.stdout)

    def test_clean_tree_passes_and_exceptions_hold(self):
        self.write("ok.md", "Read only the listed files. Encode as UTF-8. Hash with SHA-256.\nSchema draft 2020-12 applies.\n")
        self.write("hygiene.sh", "this copy of the script itself is skipped: %s\n" % WORD)
        self.write("node_modules/x/README.md", "%s\n" % DATE)
        done = hygiene(self.harness)
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertEqual(done.stdout, "")

    def test_workspace_mode_scans_client_names_and_product_layer(self):
        ws = Path(self.tmp.name) / "ws"
        (ws / "product" / "code-map").mkdir(parents=True)
        (ws / "product" / "client.config.yaml").write_text(
            "client: %s\nstacks:\n  backend:\n    repo: %s\n  web:\n    repo: shop\n" % (CLIENT, REPO))
        self.write("claude/agents/worker.md", "When %s names a table, record it.\n" % CLIENT)
        self.write("claude/skills/reduce.md", "The %s module has helpers.\nThe shop is closed.\n" % REPO)
        self.write("claude/skills/ok.md", "Start the backend before the web stack.\n")
        (ws / "product" / "conventions.md").write_text("Errors bubble up.\nDecided on %s.\n" % DATE)
        (ws / "product" / "code-map" / "cart.md").write_text("Entry point is cart/views. %s\n" % TICKET)
        (ws / "product" / "cost-log.md").write_text("slug | tokens\nx | 1 | %s\n" % DATE)
        done = hygiene(self.harness, ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("client  %s:1:" % (self.harness / "claude/agents/worker.md"), done.stdout)
        self.assertIn("client  %s:1:" % (self.harness / "claude/skills/reduce.md"), done.stdout)
        self.assertIn("client  %s:2:" % (self.harness / "claude/skills/reduce.md"), done.stdout)
        self.assertNotIn("ok.md", done.stdout)
        self.assertIn("date  %s:2:" % (ws / "product/conventions.md"), done.stdout)
        self.assertIn("ticket  %s:1:" % (ws / "product/code-map/cart.md"), done.stdout)
        self.assertNotIn("cost-log.md", done.stdout)

    def test_this_repo_is_clean(self):
        done = hygiene(ROOT)
        self.assertEqual(done.returncode, 0, done.stdout)
