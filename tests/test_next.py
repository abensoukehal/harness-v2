import json
import tempfile
import unittest
from pathlib import Path

from helpers import MONO_CONFIG, TAIL, env_workspace, run
from harness.config import load_state, save_state, state_path

ASK = {"where": "The export button is on the orders screen.", "stuck": "Two formats could apply and the spec names neither.",
       "tried": ["Both formats"], "question": "Which format should the export use?",
       "options": [{"letter": "A", "text": "Comma separated", "recommended": True}, {"letter": "B", "text": "Tab separated", "recommended": False}],
       "still_running": "the other sub-tasks", "detail": "product/features/hello"}


def st(id_, stack, repo, status="pending", **extra):
    base = {"id": id_, "stack": stack, "status": status, "attempts": 0, "interruptions": 0,
            "worktree": ".worktrees/hello/" + repo, "exit_criteria": [{"kind": "lint"}], "goal": "Goal of " + id_}
    base.update(extra)
    return base


class NextRound(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))

    def set_subtasks(self, subtasks):
        state = load_state(self.ws, "hello")
        state["subtasks"] = subtasks
        save_state(self.ws, "hello", state)

    def next(self):
        done = run("next", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def statuses(self):
        return {s["id"]: s["status"] for s in load_state(self.ws, "hello")["subtasks"]}

    def test_three_failures_block_one_and_the_run_continues(self):
        self.set_subtasks([
            st("st-01", "api", "svc", status="blocked", attempts=3, reason="criteria", last_error="assert 3 == 2"),
            st("st-02", "web", "web", depends_on=["st-01"]),
            st("st-03", "web", "web"),
        ])
        round1 = self.next()
        self.assertEqual(round1, {"ready": ["st-03"], "skipped": ["st-02"], "pending": 1})
        self.assertEqual(self.statuses(), {"st-01": "blocked", "st-02": "skipped", "st-03": "pending"})
        state = load_state(self.ws, "hello")
        self.assertEqual([s for s in state["subtasks"] if s["id"] == "st-02"][0]["reason"], "depends on st-01")
        state["subtasks"][2].update(status="done", attempts=1, commit="a" * 40,
                                    cost={"tokens_in": 0, "tokens_out": 1, "duration_s": 1})
        save_state(self.ws, "hello", state)
        self.assertEqual(self.next(), {"ready": [], "skipped": [], "pending": 0})

    def test_a_cycle_in_the_state_is_refused_before_the_round(self):
        """plan.md cannot carry a cycle, but a resume or a state.json edited by hand can (14.7)."""
        state = load_state(self.ws, "hello")
        state["subtasks"] = [st("st-01", "api", "svc", depends_on=["st-02"]), st("st-02", "web", "web", depends_on=["st-01"])]
        state_path(self.ws, "hello").write_text(json.dumps(state, indent=2) + "\n")
        done = run("next", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1, done.stdout)
        self.assertIn("depends_on cycle: st-01 > st-02 > st-01", done.stderr)

    def test_needs_parks_the_subtask_and_the_others_run(self):
        self.set_subtasks([
            st("st-01", "api", "svc", status="blocked", attempts=1, reason="needs", ask=ASK),
            st("st-02", "web", "web"),
            st("st-03", "api", "svc", depends_on=["st-01"]),
        ])
        self.assertEqual(self.next(), {"ready": ["st-02"], "skipped": ["st-03"], "pending": 1})
        rendered = run("ask", "hello", "st-01", ws=self.ws)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        self.assertIn("A. Comma separated (recommended)", rendered.stdout)
        self.assertTrue(rendered.stdout.rstrip().endswith("Detail: product/features/hello"))

    def test_one_per_repo_and_four_at_most(self):
        self.set_subtasks([st("st-01", "api", "svc"), st("st-02", "api", "svc"), st("st-03", "web", "web")])
        self.assertEqual(self.next()["ready"], ["st-01", "st-03"])
        config = "client: example-many\nstacks:\n" + "".join(
            "  s%d:\n    repo: r%d\n    path: repos/r%d\n    commands: {dev: sleep 60}\n    health: [{log: never}]\n    health_timeout_s: 5\n" % (i, i, i)
            for i in range(1, 6)) + TAIL % "{s1: t, s2: t, s3: t, s4: t, s5: t}"
        (self.ws / "product/client.config.yaml").write_text(config)
        self.set_subtasks([st("st-0%d" % i, "s%d" % i, "r%d" % i) for i in range(1, 6)])
        self.assertEqual(self.next()["ready"], ["st-01", "st-02", "st-03", "st-04"])

    def test_left_running_becomes_blocked_not_a_halt(self):
        self.set_subtasks([st("st-01", "api", "svc", status="running"), st("st-02", "web", "web")])
        self.assertEqual(self.next(), {"ready": ["st-02"], "skipped": [], "pending": 1})
        self.assertEqual(self.statuses()["st-01"], "blocked")
