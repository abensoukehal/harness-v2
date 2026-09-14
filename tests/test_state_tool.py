import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import BIN, make_workspace, make_repo, run
from harness.config import load_state


class StateTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = make_workspace(Path(self.tmp.name))
        (self.ws / "product/client.config.yaml").write_text((self.ws / "product/client.config.yaml").read_text().replace("<client>", "x"))
        run("new", "hello", ws=self.ws)

    def update(self, patch):
        env = {"HARNESS_WORKSPACE": str(self.ws), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        return subprocess.run([str(BIN / "state"), "update", "hello", "-"], input=json.dumps(patch), env=env, capture_output=True, text=True)

    def test_init_get_update(self):
        first = run("state", "init", "hello", "service", ws=self.ws)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertIn("now", json.loads(first.stdout))
        again = run("state", "init", "hello", "service", ws=self.ws)
        self.assertEqual(again.returncode, 1)
        self.assertIn("refusing", again.stderr)
        got = json.loads(run("state", "get", "hello", ws=self.ws).stdout)
        self.assertEqual((got["kind"], got["phase"], got["subtasks"]), ("service", "ingestion", []))

        base = {"id": "st-01", "stack": "backend", "status": "pending", "attempts": 0, "interruptions": 0,
                "worktree": ".worktrees/hello/backend", "exit_criteria": [{"kind": "lint"}]}
        done = self.update({"phase": "build", "subtasks": [base], "decisions": ["st-01 · a · spec"]})
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("now", json.loads(done.stdout))
        done = self.update({"subtasks": [{"id": "st-01", "status": "running"}], "decisions": ["st-01 · b · design"], "frictions": ["f"]})
        self.assertEqual(done.returncode, 0, done.stderr)
        state = load_state(self.ws, "hello")
        self.assertEqual(state["phase"], "build")
        self.assertEqual(state["subtasks"], [dict(base, status="running")])
        self.assertEqual(state["decisions"], ["st-01 · a · spec", "st-01 · b · design"])
        self.assertEqual(state["frictions"], ["f"])

        before = (self.ws / "product/features/hello/state.json").read_text()
        bad = self.update({"subtasks": [{"id": "st-01", "status": "done"}]})
        self.assertEqual(bad.returncode, 1)
        self.assertIn("subtasks/0/commit", bad.stderr)
        self.assertEqual((self.ws / "product/features/hello/state.json").read_text(), before)
        self.assertEqual(self.update({"phase": "nope"}).returncode, 1)
        self.assertEqual(self.update("not json").returncode, 1)

    def test_one_observation_per_subtask(self):
        run("state", "init", "hello", "service", ws=self.ws)
        base = {"id": "st-01", "stack": "backend", "status": "pending", "attempts": 0, "interruptions": 0,
                "worktree": ".worktrees/hello/backend", "exit_criteria": [{"kind": "lint"}]}
        self.update({"subtasks": [base]})
        first = self.update({"subtasks": [{"id": "st-01", "noted": "orders carry a soft delete flag the plan does not mention"}]})
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.update({"subtasks": [{"id": "st-01", "status": "running", "noted": "the tax rate is read from a second table"}]})
        self.assertEqual(second.returncode, 0, second.stderr)
        st = load_state(self.ws, "hello")["subtasks"][0]
        self.assertEqual(st["noted"], "orders carry a soft delete flag the plan does not mention")
        self.assertEqual(st["status"], "running")

    def test_an_observation_carrying_a_path_or_code_is_refused(self):
        run("state", "init", "hello", "service", ws=self.ws)
        base = {"id": "st-01", "stack": "backend", "status": "pending", "attempts": 0, "interruptions": 0,
                "worktree": ".worktrees/hello/backend", "exit_criteria": [{"kind": "lint"}]}
        self.update({"subtasks": [base]})
        for line in ["the flag lives in app/models/order.py", "the filter calls `soft_deleted`", "two lines\nof it", "x" * 161]:
            bad = self.update({"subtasks": [{"id": "st-01", "noted": line}]})
            self.assertEqual(bad.returncode, 1, line)
            self.assertIn("subtasks/0/noted", bad.stderr, line)
        self.assertNotIn("noted", load_state(self.ws, "hello")["subtasks"][0])

    def test_since_becomes_duration(self):
        run("state", "init", "hello", "service", ws=self.ws)
        self.update({"subtasks": [{"id": "st-01", "stack": "backend", "status": "pending", "attempts": 0, "interruptions": 0,
                                   "worktree": ".worktrees/hello/backend", "exit_criteria": [{"kind": "lint"}]}]})
        done = self.update({"subtasks": [{"id": "st-01", "status": "done", "attempts": 1, "commit": "a" * 40,
                                          "cost": {"tokens_in": 0, "tokens_out": 5, "lines_added": 1, "duration_s": 0}, "_since": 1}]})
        self.assertEqual(done.returncode, 0, done.stderr)
        st = load_state(self.ws, "hello")["subtasks"][0]
        self.assertNotIn("_since", st)
        self.assertGreater(st["cost"]["duration_s"], 1000)
