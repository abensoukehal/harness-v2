import tempfile
import unittest
from pathlib import Path

from helpers import ROOT, env_workspace, run, sh


class RetroTree(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ws = env_workspace(root)
        self.remote = root / "engine.git"
        sh("git", "clone", "-q", "--bare", str(ROOT), str(self.remote), cwd=root)
        sh("git", "remote", "set-url", "origin", str(self.remote), cwd=self.ws / "harness")
        self.pin = (self.ws / "product/harness.pin").read_text().strip()
        ahead = root / "ahead"
        sh("git", "clone", "-q", str(self.remote), str(ahead), cwd=root)
        (ahead / "STATE.md").write_text("engine moved on\n")
        sh("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "STATE.md", cwd=ahead)
        sh("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "Move on", cwd=ahead)
        sh("git", "push", "-q", "origin", "HEAD", cwd=ahead)
        self.remote_head = sh("git", "rev-parse", "HEAD", cwd=ahead)

    def test_clone_at_the_remote_head_and_harness_stays_at_the_pin(self):
        done = run("retro-tree", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        tree = Path(done.stdout.strip().splitlines()[-1])
        self.assertEqual(tree, self.ws / ".retro/hello")
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=tree), self.remote_head, "fresh from the remote, not from the pin")
        self.assertEqual(sh("git", "remote", "get-url", "origin", cwd=tree), str(self.remote))
        self.assertTrue((tree / "node_modules/ajv").is_dir())
        (tree / "STATE.md").write_text("retro edit\n")
        sh("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qam", "Retro edit", cwd=tree)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=self.ws / "harness"), self.pin, "the workspace's harness never moves")
        self.assertEqual(run("state", "get", "hello", ws=self.ws).returncode, 0, "every tool still runs after the retro")
        again = run("retro-tree", "hello", ws=self.ws)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=tree), self.remote_head, "a second call starts over")

    def test_unreachable_remote_falls_back_to_the_pin(self):
        sh("git", "remote", "set-url", "origin", str(self.remote) + "-gone", cwd=self.ws / "harness")
        done = run("retro-tree", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("unreachable: cloned harness/ at the pin instead", done.stdout)
        tree = self.ws / ".retro/hello"
        self.assertEqual(sh("git", "rev-parse", "HEAD", cwd=tree), self.pin)
        self.assertEqual(sh("git", "remote", "get-url", "origin", cwd=tree), str(self.remote) + "-gone")
