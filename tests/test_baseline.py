import tempfile
import unittest
from pathlib import Path

from helpers import env_config, env_workspace, run
from harness.baseline import did_not_run, failing_tests
from harness.config import load_state
from harness.env import stop_all

RED = ("printf '%s\\n' 'tests/test_items.py::test_list PASSED' 'FAILED tests/test_items.py::test_sorted - assert 1 == 2' "
       "'TAP version 13' '    not ok 3 - lists items sorted by title' 'ok 4 - marks done' 'FAILED tests/test_items.py::test_sorted'; exit 1")
NAMELESS = "echo 'Error: cannot find module'; exit 2"
BROKEN = ("printf '%s\\n' 'Error: Cannot find module /repo/tests' 'MODULE_NOT_FOUND' "
          "'\\u2716 tests (40.071709ms)' 'i pass 0' 'i fail 1' '\\u2716 failing tests:'; exit 1")


class Baseline(unittest.TestCase):
    def test_runner_lines_become_names(self):
        out = "\n".join(["FAILED tests/a.py::test_x - boom", "  not ok 2 - sorted list # TODO", "✖ renders the title (12ms)", "  3) [chromium] › items.spec.ts:4 › archives an item ───", "--- FAIL: TestSum", "ok 5 - fine"])
        self.assertEqual(failing_tests(out), ["tests/a.py::test_x", "sorted list", "renders the title", "archives an item", "TestSum"])

    def test_a_runner_heading_is_not_a_test_name(self):
        out = "\n".join(["✖ tests (40.071709ms)", "✖ failing tests:", "✖ renders the title (12.5 ms)", "  not ok 1 - Failures:"])
        self.assertEqual(failing_tests(out), ["tests", "renders the title"])
        self.assertIsNone(did_not_run("✔ ok\nℹ pass 3\nℹ fail 0", 0, []))
        self.assertIn("the runner did not start", did_not_run("Error: Cannot find module 'x'\nℹ pass 0", 1, ["tests"]))
        self.assertIsNone(did_not_run("Cannot find module 'x' was the assertion\nℹ pass 7", 1, ["a test"]), "a real suite that mentions the words still ran")
        self.assertIn("exited 2 and named no failing test", did_not_run("boom", 2, []))

    def test_a_suite_that_cannot_run_blocks_the_phase(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d), config=env_config(extra="client_tests: {api: \"%s\"}" % BROKEN))
            self.addCleanup(stop_all, ws, "hello")
            done = run("baseline", "hello", ws=ws)
            self.assertEqual(done.returncode, 1)
            self.assertIn("stack api: no baseline, the runner did not start", done.stderr)
            self.assertIn("Cannot find module", done.stderr)
            self.assertIn("Fix the client_tests command for api", done.stderr)
            state = load_state(ws, "hello")
            self.assertNotIn("client_test_baseline", state, "no baseline is recorded, not a wrong one")
            self.assertIn("baseline · api suite did not run · environment ·", state["frictions"][0])

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

    def test_only_declared_secrets_are_redacted_from_the_suite_output(self):
        # An env file holds config as well as secrets. Redacting all of it eats version numbers and paths, and the
        # suite's own failure becomes unreadable at the moment someone has to act on it (9.3).
        with tempfile.TemporaryDirectory() as d:
            echo = "echo 'version 1.0.0 built by ci with abcd1234'"
            ws = env_workspace(Path(d), config=env_config(extra="client_tests: {api: \"%s\"}" % echo))
            self.addCleanup(stop_all, ws, "hello")
            (ws / "secrets/api/api.env").write_text("API_KEY=abcd1234\nAPP_VERSION=1.0.0\nBUILT_BY=ci\n")
            done = run("baseline", "hello", ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            log = (ws / ".run/hello/baseline-api.log").read_text()
            self.assertIn("[REDACTED API_KEY]", log, "the declared secret is redacted")
            self.assertIn("version 1.0.0 built by ci", log, "undeclared config is not a secret and stays readable")

    def test_a_suite_that_fails_without_naming_a_test_blocks_too(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d), config=env_config(extra="client_tests: {api: \"%s\"}" % NAMELESS))
            self.addCleanup(stop_all, ws, "hello")
            done = run("baseline", "hello", ws=ws)
            self.assertEqual(done.returncode, 1)
            state = load_state(ws, "hello")
            self.assertNotIn("client_test_baseline", state)
            self.assertIn("baseline · api suite did not run · environment ·", state["frictions"][0])
