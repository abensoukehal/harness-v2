import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import BIN, sh


class TagPush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote = root / "origin.git"
        sh("git", "init", "-q", "--bare", str(self.remote), cwd=root)
        self.repo = root / "engine"
        self.repo.mkdir()
        sh("git", "init", "-q", cwd=self.repo)
        sh("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=self.repo)
        sh("git", "config", "user.email", "t@example.com", cwd=self.repo)
        sh("git", "config", "user.name", "t", cwd=self.repo)
        sh("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        (self.repo / "STATE.md").write_text("one\n")
        sh("git", "add", ".", cwd=self.repo)
        sh("git", "commit", "-q", "-m", "Retro one", cwd=self.repo)

    def push(self, slug):
        return subprocess.run([str(BIN / "tag-push"), slug, "--repo", str(self.repo)], capture_output=True, text=True)

    def test_branch_first_then_tag(self):
        done = self.push("checkout-coupons")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(sh("git", "rev-parse", "main", cwd=self.remote), sh("git", "rev-parse", "HEAD", cwd=self.repo))
        self.assertEqual(sh("git", "tag", "-l", "retro/*", cwd=self.remote), "retro/checkout-coupons")
        again = self.push("checkout-coupons")
        self.assertEqual(again.returncode, 1)
        self.assertIn("one retro tag per feature", again.stderr)

    def test_refused_branch_push_leaves_no_tag_anywhere(self):
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'closed for maintenance' >&2\nexit 1\n")
        hook.chmod(0o755)
        done = self.push("checkout-coupons")
        self.assertEqual(done.returncode, 1)
        self.assertIn("refused", done.stderr)
        self.assertIn("closed for maintenance", done.stderr)
        self.assertEqual(sh("git", "tag", "-l", "retro/*", cwd=self.repo), "", "local tag deleted")
        self.assertEqual(sh("git", "tag", "-l", cwd=self.remote), "")
        self.assertEqual(subprocess.run(["git", "rev-parse", "--verify", "main"], cwd=str(self.remote), capture_output=True).returncode, 128)
