import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import BIN, ROOT, sh


def rollback(repo, *args):
    return subprocess.run([str(BIN / "rollback"), "--repo", str(repo), *args], capture_output=True, text=True)


class Rollback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / "engine"
        sh("git", "clone", "-q", str(ROOT), str(self.repo), cwd=self.tmp.name)
        sh("git", "config", "user.email", "t@example.com", cwd=self.repo)
        sh("git", "config", "user.name", "t", cwd=self.repo)
        for i, word in enumerate(["one", "two", "three"], start=1):
            (self.repo / "STATE.md").write_text(word + "\n")
            env = dict(os.environ, GIT_COMMITTER_DATE="%d-%02d-%02dT00:00:00" % (2000, 1, i),
                       GIT_AUTHOR_DATE="%d-%02d-%02dT00:00:00" % (2000, 1, i))
            subprocess.run(["git", "add", "STATE.md"], cwd=self.repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "Retro %s" % word], cwd=self.repo, check=True, env=env)
            sh("git", "tag", "retro/" + word, cwd=self.repo)

    def count(self):
        return int(sh("git", "rev-list", "--count", "HEAD", cwd=self.repo))

    def test_default_reverts_to_previous_tag_without_rewriting_history(self):
        before = self.count()
        head = sh("git", "rev-parse", "HEAD", cwd=self.repo)
        done = rollback(self.repo)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("rolled back to retro/two", done.stdout)
        self.assertEqual((self.repo / "STATE.md").read_text(), "two\n")
        self.assertEqual(self.count(), before + 1)
        self.assertEqual(sh("git", "rev-parse", "retro/three", cwd=self.repo), head)
        self.assertEqual(sh("git", "log", "-1", "--format=%s", cwd=self.repo), "Roll back engine to retro/two")
        questions = (self.repo / "OPEN_QUESTIONS.md").read_text()
        self.assertIn("## Rolled back to retro/two", questions)
        self.assertIn("Retro three", questions)
        self.assertNotIn("Retro two", questions)
        self.assertEqual(sh("git", "status", "--porcelain", cwd=self.repo), "")

    def test_explicit_tag_and_refusals(self):
        done = rollback(self.repo, "retro/one")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual((self.repo / "STATE.md").read_text(), "one\n")
        questions = (self.repo / "OPEN_QUESTIONS.md").read_text()
        self.assertIn("Retro two", questions)
        self.assertIn("Retro three", questions)
        self.assertEqual(rollback(self.repo, "retro/nope").returncode, 1)
        (self.repo / "STATE.md").write_text("dirty\n")
        dirty = rollback(self.repo)
        self.assertEqual(dirty.returncode, 1)
        self.assertIn("not clean", dirty.stderr)

    def test_no_tag_behind_head_is_refused(self):
        for tag in ["one", "two", "three"]:
            sh("git", "tag", "-d", "retro/" + tag, cwd=self.repo)
        done = rollback(self.repo)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no retro/* tag", done.stderr)
