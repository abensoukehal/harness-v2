import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run, sh
from harness.config import load_state, save_state

SUBTASK = {"id": "st-01", "stack": "api", "status": "pending", "attempts": 0, "interruptions": 0,
           "worktree": ".worktrees/hello/svc", "exit_criteria": [{"kind": "lint"}]}


class SafetyNet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        (self.ws / "product/tests/api").mkdir(parents=True)
        (self.ws / "product/tests/api/test_items.py").write_text("def test_items(): pass\n")

    def test_freeze_then_check_refuses_any_change(self):
        frozen = run("net", "freeze", "hello", ws=self.ws)
        self.assertEqual(frozen.returncode, 0, frozen.stderr)
        sha = load_state(self.ws, "hello")["net_commit"]
        self.assertEqual(sha, sh("git", "rev-parse", "HEAD", cwd=self.ws / "product"))
        self.assertEqual(run("net", "check", "hello", ws=self.ws).returncode, 0)
        (self.ws / "product/tests/api/test_items.py").write_text("def test_items(): assert False\n")
        (self.ws / "product/tests/api/test_extra.py").write_text("x = 1\n")
        done = run("net", "check", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("differs from the frozen safety net", done.stderr)
        self.assertIn("tests/api/test_items.py", done.stderr)
        self.assertIn("tests/api/test_extra.py", done.stderr)

    def test_unfrozen_net_with_subtasks_is_refused(self):
        self.assertEqual(run("net", "check", "hello", ws=self.ws).returncode, 0, "nothing planned, nothing to check")
        state = load_state(self.ws, "hello")
        state["subtasks"] = [SUBTASK]
        save_state(self.ws, "hello", state)
        done = run("net", "check", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("safety net is not frozen", done.stderr)

    def test_unfrozen_net_inside_the_safety_net_phase_is_allowed(self):
        state = load_state(self.ws, "hello")
        state["subtasks"] = [SUBTASK]
        state["phase"] = "safety_net"
        save_state(self.ws, "hello", state)
        again = run("net", "check", "hello", ws=self.ws)
        self.assertEqual(again.returncode, 0, again.stderr)
