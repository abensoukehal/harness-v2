import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run
from harness.config import load_state, save_state
from test_next import ASK, st


class Answer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        state = load_state(self.ws, "hello")
        state.update(phase="finished", delivered=True, subtasks=[
            st("st-01", "api", "svc", status="blocked", attempts=1, reason="needs", ask=ASK, goal="Export as a file"),
            st("st-02", "web", "web", status="done", attempts=1, commit="a" * 40, cost={"tokens_in": 1, "tokens_out": 1, "duration_s": 1, "lines_added": 1}),
            st("st-03", "api", "svc", status="skipped", reason="depends on st-01", depends_on=["st-01"]),
            st("st-04", "web", "web", status="skipped", reason="depends on st-03", depends_on=["st-03"]),
            st("st-05", "web", "web", status="blocked", attempts=3, reason="criteria", last_error="red"),
            st("st-06", "web", "web", status="skipped", reason="depends on st-05", depends_on=["st-05"]),
        ])
        save_state(self.ws, "hello", state)

    def test_answer_reopens_the_parked_subtask_and_its_dependents(self):
        done = run("answer", "hello", "st-01", "b", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("st-01 back to pending, reopened st-03, st-04", done.stdout)
        state = load_state(self.ws, "hello")
        by_id = {s["id"]: s for s in state["subtasks"]}
        self.assertEqual(by_id["st-01"]["status"], "pending")
        self.assertEqual(by_id["st-01"]["answer"], {"letter": "B", "text": "Tab separated"})
        self.assertNotIn("reason", by_id["st-01"])
        self.assertIn("ask", by_id["st-01"], "the question stays on record")
        self.assertEqual((by_id["st-03"]["status"], by_id["st-04"]["status"]), ("pending", "pending"))
        self.assertEqual((by_id["st-05"]["status"], by_id["st-06"]["status"]), ("blocked", "skipped"), "other blockages untouched")
        self.assertEqual(state["phase"], "build")
        self.assertIn("st-01 · Ali chose B: Tab separated · ask", state["decisions"])
        state["ports"] = {"api": 50100, "web": 50101, "db": 50102}
        save_state(self.ws, "hello", state)
        brief = run("briefing", "hello", "st-01", ws=self.ws)
        self.assertEqual(brief.returncode, 0, brief.stderr)
        self.assertIn("answer from Ali to your question: B. Tab separated", brief.stdout)

    def test_an_answer_and_a_hand_fix_both_count_as_interventions(self):
        run("answer", "hello", "st-01", "b", ws=self.ws)
        touched = load_state(self.ws, "hello")["interventions"]
        self.assertEqual(touched, [{"phase": "finished", "cause": "answered-ask",
                                    "line": "st-01 waited on a question and Ali answered B"}],
                         "recorded where the run actually was when the human reached it")
        done = run("intervene", "hello", "environment", "the api stack needed its database started by hand", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn('"interventions": 2', done.stdout)
        self.assertEqual(load_state(self.ws, "hello")["interventions"][1],
                         {"phase": "build", "cause": "environment", "line": "the api stack needed its database started by hand"})
        long = run("intervene", "hello", "environment", "x" * 200 + "\nand more", ws=self.ws)
        self.assertEqual(long.returncode, 0, long.stderr)
        self.assertEqual(load_state(self.ws, "hello")["interventions"][2]["line"], "x" * 160, "one line, and the cap")
        for bad in [("hello", "Not A Slug", "a line"), ("hello", "environment", "   "), ("hello", "environment")]:
            self.assertEqual(run("intervene", *bad, ws=self.ws).returncode, 1, str(bad))
        self.assertEqual(len(load_state(self.ws, "hello")["interventions"]), 3)

    def test_refusals(self):
        self.assertEqual(run("answer", "hello", "st-01", "D", ws=self.ws).returncode, 1)
        self.assertIn("not an option", run("answer", "hello", "st-01", "D", ws=self.ws).stderr)
        self.assertIn("not parked", run("answer", "hello", "st-05", "A", ws=self.ws).stderr)
        self.assertIn("no sub-task st-09", run("answer", "hello", "st-09", "A", ws=self.ws).stderr)
        self.assertEqual(load_state(self.ws, "hello")["subtasks"][0]["status"], "blocked")
