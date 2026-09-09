import tempfile
import unittest
from pathlib import Path

from helpers import MONO_CONFIG, env_workspace, run
from harness.config import load_state
from test_plan import PLAN


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        self.plan = self.ws / "product/features/hello/plan.md"
        self.plan.write_text(PLAN)

    def test_the_message_carries_the_goals_the_numbers_and_the_graph(self):
        done = run("review", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        text = done.stdout
        self.assertIn("hello — plan ready", text)
        self.assertIn("- Orders export as CSV through the API", text)
        self.assertIn("3 sub-tasks, at most 4 criteria on one, 0 reaching into more than one stack.", text)
        self.assertIn("A. Approve, and the build runs it.", text)
        self.assertTrue(text.rstrip().endswith("Detail: product/features/hello/plan.md product/features/hello/plan.mmd"))
        head = text.split("Detail:")[0]
        for forbidden in ["repos/", ".py", ".js", "st-01"]:
            self.assertNotIn(forbidden, head, "the summary is what Ali reads on a phone")
        graph = (self.ws / "product/features/hello/plan.mmd").read_text()
        self.assertIn("graph TD", graph)
        self.assertIn('st-02["st-02 · The export shows in the orders screen"]', graph)
        self.assertIn("st-01 --> st-02", graph)
        self.assertIn("st-02 --> st-03", graph)
        self.assertEqual(load_state(self.ws, "hello")["plan_message"], text, "the plan_ready push sends this, not plan.md")

    def test_a_goal_carrying_a_path_or_a_function_name_is_refused(self):
        for goal, problem in [("The export writes repos/svc/export.py", "which is code or a path"),
                              ("The export calls render_csv(rows)", "which is code or a path"),
                              ("The export " + "runs on " * 25, "past 160")]:
            self.plan.write_text(PLAN.replace("Orders export as CSV through the API", goal))
            done = run("review", "hello", ws=self.ws)
            self.assertEqual(done.returncode, 1, goal)
            self.assertIn("the plan review is what Ali reads on a phone", done.stderr)
            self.assertIn(problem, done.stderr, goal)
        self.plan.write_text(PLAN)
        self.assertEqual(run("review", "hello", ws=self.ws).returncode, 0)

MONO_PLAN = """# mono
kind: service

## st-01 · Orders export as CSV through the API
stack: a
files: repos/mono/apps/a/export.py, repos/mono/apps/b/table.js
depends_on: none
line_budget: 80
criteria:
- test a/test_export.py

## st-02 · The export shows in the orders screen
stack: b
files: repos/mono/apps/b/orders.js
depends_on: st-01
line_budget: 40
criteria:
- test b/test_orders.py
"""


class Monorepo(unittest.TestCase):
    """Two stacks in one repo is the only shape where a sub-task can reach into more than one stack (13.3)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name), config=MONO_CONFIG, repos=("mono",))
        self.plan = self.ws / "product/features/hello/plan.md"

    def review(self, text):
        self.plan.write_text(text)
        done = run("review", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_the_spread_counts_the_sub_tasks_reaching_into_two_stacks(self):
        self.assertIn("2 sub-tasks, at most 1 criteria on one, 1 reaching into more than one stack.",
                      self.review(MONO_PLAN))
        # The same plan with the second stack's file taken off st-01 keeps every sub-task in one stack.
        one = MONO_PLAN.replace("repos/mono/apps/a/export.py, repos/mono/apps/b/table.js", "repos/mono/apps/a/export.py")
        self.assertIn("2 sub-tasks, at most 1 criteria on one, 0 reaching into more than one stack.", self.review(one))


if __name__ == "__main__":
    unittest.main()
