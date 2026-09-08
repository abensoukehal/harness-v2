import os
import stat
import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, make_workspace, run, sh


class Init(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_layout(self):
        ws = make_workspace(self.root, "example-a")
        for rel in ["CLAUDE.md", "secrets", "harness/claude", "product/client.config.yaml", "product/conventions.md",
                    "product/code-map", "product/tests", "product/cost-log.md", "product/features", "product/.git", "repos", ".worktrees"]:
            self.assertTrue((ws / rel).exists(), rel)
        self.assertEqual(stat.S_IMODE(os.stat(ws / "secrets").st_mode), 0o700)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=ws / "harness"), sh("git", "rev-parse", "HEAD", cwd=ROOT))
        claude_files = [p for p in ws.rglob("CLAUDE.md") if "harness" not in p.relative_to(ws).parts]
        self.assertEqual(claude_files, [ws / "CLAUDE.md"])
        self.assertIn("example-a", (ws / "CLAUDE.md").read_text())
        for name in ["workflows", "agents", "skills"]:
            link = ws / ".claude" / name
            self.assertTrue(link.is_symlink(), name)
            self.assertEqual(link.resolve(), (ws / "harness" / "claude" / name).resolve())
        self.assertEqual(run("validate", ws / "product" / "client.config.yaml").returncode, 0)
        self.assertEqual((ws / "product" / "harness.pin").read_text().strip(), sh("git", "rev-parse", "HEAD", cwd=ws / "harness"))

    def test_refuses_existing_and_bad_names(self):
        make_workspace(self.root, "example-b")
        self.assertEqual(run("init", "example-b", "--root", self.root).returncode, 1)
        bad = run("init", "Bad_Name", "--root", self.root)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("client name", bad.stderr)


class Link(unittest.TestCase):
    def test_idempotent_and_refuses_real_dir(self):
        with tempfile.TemporaryDirectory() as d:
            ws = make_workspace(Path(d), "example-c")
            self.assertEqual(run("link", ws).returncode, 0)
            self.assertTrue((ws / ".claude" / "skills").is_symlink())
            (ws / ".claude" / "skills").unlink()
            (ws / ".claude" / "skills").mkdir()
            done = run("link", ws)
            self.assertEqual(done.returncode, 1)
            self.assertIn("real directory", done.stderr)


class Pin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ws = make_workspace(self.root, "example-p")
        self.pinned = sh("git", "rev-parse", "HEAD", cwd=self.ws / "harness")
        # harness/ drifts: a local commit on top of the pin
        (self.ws / "harness" / "STATE.md").write_text("drift\n")
        sh("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "STATE.md", cwd=self.ws / "harness")
        sh("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "Drift", cwd=self.ws / "harness")
        self.drifted = sh("git", "rev-parse", "HEAD", cwd=self.ws / "harness")

    def test_link_and_tools_refuse_a_drifted_harness(self):
        for cmd, args in [("link", [self.ws]), ("state", ["get", "hello"]), ("up", ["hello"]), ("plan", ["hello"])]:
            done = run(cmd, *args, ws=self.ws)
            self.assertEqual(done.returncode, 1, cmd)
            self.assertIn("harness/ is at %s" % self.drifted[:12], done.stderr, cmd)
            self.assertIn(self.pinned[:12], done.stderr, cmd)
        self.assertEqual(run("cleanup", "hello", ws=self.ws).returncode, 0, "cleanup never refuses")

    def test_pin_moves_harness_and_the_pin_together(self):
        done = run("pin", "example-p", self.drifted, "--root", self.root)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.strip(), self.drifted)
        self.assertEqual((self.ws / "product" / "harness.pin").read_text().strip(), self.drifted)
        self.assertEqual(run("link", self.ws).returncode, 0)
        back = run("pin", "example-p", self.pinned, "--root", self.root)
        self.assertEqual(back.returncode, 0, back.stderr)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=self.ws / "harness"), self.pinned)
        self.assertEqual(run("pin", "example-p", "nope", "--root", self.root).returncode, 1)
        self.assertEqual(run("pin", "nobody", "--root", self.root).returncode, 1)

    def test_missing_pin_is_named(self):
        (self.ws / "product" / "harness.pin").unlink()
        done = run("state", "get", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no product/harness.pin", done.stderr)


class New(unittest.TestCase):
    def test_creates_feature_folder_once(self):
        with tempfile.TemporaryDirectory() as d:
            ws = make_workspace(Path(d), "example-d")
            self.assertEqual(run("new", "checkout-coupons", ws=ws).returncode, 0)
            folder = ws / "product" / "features" / "checkout-coupons"
            spec = (folder / "spec.md").read_text()
            for heading in ["# checkout-coupons", "## Outcome", "## Pain points", "## Scope", "## Out of scope", "## Constraints", "## Open questions"]:
                self.assertIn(heading, spec)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ["design", "spec.md"])
            self.assertEqual(list((folder / "design").iterdir()), [])
            again = run("new", "checkout-coupons", ws=ws)
            self.assertEqual(again.returncode, 1)
            self.assertIn("already exists", again.stderr)
            self.assertEqual(run("new", "Bad Slug", ws=ws).returncode, 1)
