import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run, sh
from harness import worktree
from harness.config import load_config, load_state, save_state

SUBJECT = "Add coupon validation to checkout form"


def commits(wt):
    return sh("git", "rev-list", "--count", "HEAD", cwd=wt)


class Commit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        cfg, state = load_config(self.ws), load_state(self.ws, "hello")
        worktree.ensure(self.ws, cfg, "hello", state)
        save_state(self.ws, "hello", state)
        self.wt = self.ws / ".worktrees/hello/svc"

    def test_commits_with_fixed_identity_and_no_trailer(self):
        (self.wt / "coupon.py").write_text("def validate(code): return code.isalnum()\n")
        # A hostile global config: a hook that appends a trailer, and signing turned on.
        hooks = Path(self.tmp.name) / "global-hooks"
        hooks.mkdir()
        (hooks / "prepare-commit-msg").write_text("#!/bin/sh\necho 'Co-Authored-By: Bot <bot@example.com>' >> \"$1\"\n")
        (hooks / "prepare-commit-msg").chmod(0o755)
        gitconfig = Path(self.tmp.name) / "gitconfig"
        gitconfig.write_text("[core]\n\thooksPath = %s\n[commit]\n\tgpgsign = true\n[user]\n\tname = Global Person\n\temail = global@example.com\n" % hooks)
        env = dict(os.environ, HARNESS_WORKSPACE=str(self.ws), GIT_CONFIG_GLOBAL=str(gitconfig))
        done = subprocess.run([str(run.__globals__["BIN"] / "commit"), "hello", "svc", SUBJECT, "--body", "Codes are checked before the discount is applied."],
                              env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        sha = done.stdout.strip()
        self.assertEqual(sha, sh("git", "rev-parse", "HEAD", cwd=self.wt))
        self.assertEqual(sh("git", "log", "-1", "--format=%an <%ae> %cn <%ce>", cwd=self.wt),
                         "Example Dev <dev@example.com> Example Dev <dev@example.com>")
        body = sh("git", "log", "-1", "--format=%B", cwd=self.wt)
        self.assertEqual(body.splitlines()[0], SUBJECT)
        self.assertNotIn("Co-Authored-By", body)
        self.assertIn("Codes are checked", body)

    def test_refuses_harness_paths_and_commits_nothing(self):
        (self.wt / "good.py").write_text("ok\n")
        (self.wt / "state.json").write_text("{}\n")
        (self.wt / "notes.harness.md").write_text("x\n")
        (self.wt / ".claude").mkdir()
        (self.wt / ".claude" / "settings.json").write_text("{}\n")
        (self.wt / "CLAUDE.md").write_text("x\n")
        (self.wt / ".env").write_text("SECRET=1\n")
        (self.wt / "product").mkdir()
        (self.wt / "product" / "t.py").write_text("x\n")
        os.symlink("/etc/hosts", self.wt / "escape")
        before = commits(self.wt)
        done = run("commit", "hello", "svc", SUBJECT, ws=self.ws)
        self.assertEqual(done.returncode, 1)
        for path in ["state.json", "notes.harness.md", ".claude/settings.json", "CLAUDE.md", ".env", "product/t.py", "escape"]:
            self.assertIn(path, done.stderr)
        self.assertNotIn("good.py", done.stderr)
        self.assertEqual(commits(self.wt), before)
        self.assertEqual(sh("git", "diff", "--cached", "--name-only", cwd=self.wt), "")

    def test_refuses_bad_messages(self):
        (self.wt / "good.py").write_text("ok\n")
        cases = [
            ("st-01 done", "sub-task id"),
            ("Fix " + "ACME" + "-" + "123", "ticket id"),
            ("Finish the hello flow", "feature slug"),
            ("Let the agent add coupons", "forbidden word"),
            ("Add AI summaries", "forbidden word"),
            ("Update state.json", "internal file"),
            ("Add coupons on " + "-".join(["2024", "05", "01"]), "date"),
            ("", "empty subject"),
            ("Add coupons\nsecond line", "one line"),
            ("A" * 73, "longer than"),
        ]
        for message, reason in cases:
            done = run("commit", "hello", "svc", message, ws=self.ws)
            self.assertEqual(done.returncode, 1, message)
            self.assertIn(reason, done.stderr, message)
        self.assertEqual(commits(self.wt), "1")
        self.assertEqual(run("commit", "hello", "svc", SUBJECT, ws=self.ws).returncode, 0)
        self.assertEqual(run("commit", "hello", "svc", SUBJECT, ws=self.ws).returncode, 1)  # nothing left to commit
