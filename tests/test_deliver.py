import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run, sh
from harness.config import load_config, load_state, save_state
from harness import worktree
from test_next import st

DONE = dict(status="done", attempts=1, commit=None, cost={"tokens_in": 1, "tokens_out": 1, "duration_s": 1, "lines_added": 3})


class Deliver(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.ws = env_workspace(root)
        for repo in ["svc", "web"]:
            bare = root / (repo + ".git")
            sh("git", "init", "-q", "--bare", str(bare), cwd=root)
            sh("git", "remote", "add", "origin", str(bare), cwd=self.ws / "repos" / repo)
        cfg, state = load_config(self.ws), load_state(self.ws, "hello")
        worktree.ensure(self.ws, cfg, "hello", state)
        state["subtasks"] = [st("st-01", "api", "svc", goal="Orders export"), st("st-02", "web", "web", goal="Export button")]
        save_state(self.ws, "hello", state)
        self.svc = self.ws / ".worktrees/hello/svc"

    def land(self, id_="st-01"):
        (self.svc / "export.py").write_text("print('x')\n")
        sh("git", "add", ".", cwd=self.svc)
        sh("git", "-c", "user.email=t@e.com", "-c", "user.name=t", "commit", "-q", "-m", "Add export", cwd=self.svc)
        state = load_state(self.ws, "hello")
        for s in state["subtasks"]:
            if s["id"] == id_:
                s.update(DONE, commit=sh("git", "rev-parse", "HEAD", cwd=self.svc))
        save_state(self.ws, "hello", state)

    def test_nothing_done_is_refused_and_recorded(self):
        done = run("deliver", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("nothing to deliver: no sub-task is done", done.stderr)
        self.assertIn("the branch matches main in svc, web", done.stderr)
        state = load_state(self.ws, "hello")
        self.assertIs(state["delivered"], False)
        self.assertIn("delivery · nothing to deliver · no sub-task is done", state["frictions"][0])
        self.assertEqual(sh("git", "branch", "-a", cwd=self.ws.parent / "svc.git"), "", "nothing reached the remote")

    def test_a_done_subtask_with_an_empty_diff_is_refused(self):
        state = load_state(self.ws, "hello")
        state["subtasks"][0].update(DONE, commit="a" * 40)
        save_state(self.ws, "hello", state)
        done = run("deliver", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertNotIn("no sub-task is done", done.stderr)
        self.assertIn("the branch matches main in svc, web", done.stderr)
        self.assertIs(load_state(self.ws, "hello")["delivered"], False)

    def test_one_landed_subtask_delivers_every_worktree(self):
        self.land()
        done = run("deliver", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("svc: feature/hello pushed", done.stdout)
        self.assertIn("web: feature/hello pushed", done.stdout)
        self.assertIs(load_state(self.ws, "hello")["delivered"], True)
        self.assertIn("feature/hello", sh("git", "branch", "--list", "feature/hello", cwd=self.ws.parent / "svc.git"))

    def test_a_refused_push_is_a_friction_not_a_silent_pass(self):
        self.land()
        sh("git", "remote", "set-url", "origin", "/nowhere/nothing.git", cwd=self.ws / "repos/svc")
        done = run("deliver", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("push of feature/hello from .worktrees/hello/svc refused", done.stderr)
        state = load_state(self.ws, "hello")
        self.assertIs(state["delivered"], False)
        self.assertIn("delivery · push of svc refused ·", state["frictions"][0])

    def test_report_status_counts_skipped_like_blocked(self):
        state = load_state(self.ws, "hello")
        state.update(phase="finished", delivered=False)
        save_state(self.ws, "hello", state)
        self.assertTrue(run("report", "hello", ws=self.ws).stdout.startswith("hello — nothing landed\n"))
        self.land()
        for delivered, skipped, expected in [(False, True, "partial"), (True, True, "done with gaps"), (True, False, "done")]:
            state = load_state(self.ws, "hello")
            state.update(phase="finished", delivered=delivered)
            state["subtasks"][1].update(status="skipped" if skipped else "done", reason="depends on st-01")
            if not skipped:
                state["subtasks"][1].update(DONE, commit="b" * 40)
                state["subtasks"][1].pop("reason", None)
            save_state(self.ws, "hello", state)
            self.assertTrue(run("report", "hello", ws=self.ws).stdout.startswith("hello — %s\n" % expected), expected)
