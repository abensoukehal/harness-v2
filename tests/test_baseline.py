import tempfile
import unittest
from pathlib import Path

from helpers import env_config, env_workspace, run
from harness.baseline import failing_tests
from harness.config import load_state
from harness.env import stop_all

RED = ("printf '%s\\n' 'tests/test_items.py::test_list PASSED' 'FAILED tests/test_items.py::test_sorted - assert 1 == 2' "
       "'TAP version 13' '    not ok 3 - lists items sorted by title' 'ok 4 - marks done' 'FAILED tests/test_items.py::test_sorted'; exit 1")
NAMELESS = "echo 'Error: cannot find module'; exit 2"


class Baseline(unittest.TestCase):
    def test_runner_lines_become_names(self):
        out = "\n".join(["FAILED tests/a.py::test_x - boom", "  not ok 2 - sorted list # TODO", "✖ renders the title (12ms)", "  3) [chromium] › items.spec.ts:4 › archives an item ───", "--- FAIL: TestSum", "ok 5 - fine"])
        self.assertEqual(failing_tests(out), ["tests/a.py::test_x", "sorted list", "renders the title", "archives an item", "TestSum"])

    def test_names_not_directories_land_in_state(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d), config=env_config(extra="client_tests: {api: \"%s\", web: \"%s\"}" % (RED, "echo all green")))
            self.addCleanup(stop_all, ws, "hello")
            done = run("baseline", "hello", ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("api: 2 failing at the start: tests/test_items.py::test_sorted, lists items sorted by title", done.stdout)
            self.assertIn("web: 0 failing at the start", done.stdout)
            state = load_state(ws, "hello")
            self.assertEqual(state["client_test_baseline"], {"api": ["tests/test_items.py::test_sorted", "lists items sorted by title"], "web": []})
            self.assertEqual(state["frictions"], [])
            self.assertTrue((ws / ".worktrees/hello/svc").exists(), "the suite ran in the feature worktree")

    def test_a_suite_that_fails_without_naming_a_test_is_a_friction(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d), config=env_config(extra="client_tests: {api: \"%s\"}" % NAMELESS))
            self.addCleanup(stop_all, ws, "hello")
            self.assertEqual(run("baseline", "hello", ws=ws).returncode, 0)
            state = load_state(ws, "hello")
            self.assertEqual(state["client_test_baseline"], {"api": []})
            self.assertIn("baseline · api suite exited 2 with no test name recognised", state["frictions"][0])
            self.assertIn("cannot find module", state["frictions"][0])
