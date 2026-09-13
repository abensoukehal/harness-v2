import json
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from helpers import BIN, env_workspace, run
from harness.config import load_state, save_state
from test_next import ASK, st

COST = {"tokens_in": 100, "tokens_out": 50, "duration_s": 30, "lines_added": 12}


class Inbox(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        Inbox.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class Report(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        (self.ws / "product/features/hello/spec-gaps.md").write_text("# gaps\n\n## Which format wins?\nAssumed: comma, the common case.\nAffects: st-01\nPinned: st-01 lint\n\n## Empty export?\nAssumed: a header row and nothing else.\nAffects: st-01\nPinned: st-01 lint\n")
        state = load_state(self.ws, "hello")
        state.update(phase="finished", delivered=True, wall_time_s=300, subtasks=[
            st("st-01", "api", "svc", status="done", attempts=1, commit="a" * 40, cost=COST, goal="Orders export as CSV"),
            st("st-02", "web", "web", status="blocked", attempts=3, reason="criteria", last_error="assert 3 == 2", goal="The export button shows on the orders screen"),
            st("st-03", "web", "web", status="skipped", reason="depends on st-02", depends_on=["st-02"], goal="Done exports are struck through"),
            st("st-04", "api", "svc", status="blocked", attempts=1, reason="needs", ask=ASK, goal="Each row carries a summary"),
        ])
        save_state(self.ws, "hello", state)

    def test_five_blocks_with_blocked_subtasks(self):
        done = run("report", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        text = done.stdout
        self.assertEqual((self.ws / "product/features/hello/report.md").read_text(), text)
        self.assertTrue(text.startswith("hello — done with gaps\n"))
        blocks = ["What works now.", "What didn't land.", "Assumptions I made.", "What it cost.", "Next.", "Detail:"]
        positions = [text.index(b) for b in blocks]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(text.rstrip().endswith("product/features/hello/gaps/"))
        for line in ["- Orders export as CSV", "- The export button shows on the orders screen: its checks stayed red after three attempts",
                     "- Done exports are struck through: waits on the export button shows on the orders screen",
                     "- Each row carries a summary: it needs an answer, below", "A. Comma separated (recommended)", "- comma, the common case.", "- a header row and nothing else.",
                     "150 tokens (0 distinct), 300 s wall time, 4 sub-tasks, 5 attempts, 2 blocked.", "No three earlier runs to compare against.",
                     "Answer the question above first.", "Open a PR from feature/hello."]:
            self.assertIn(line, text, line)
        for absent in ["repos/", "assert 3 == 2", "st-0"]:
            self.assertNotIn(absent, text.split("Detail:")[0], absent)
        self.assertEqual(text.count("Detail:"), 1)
        log = (self.ws / "product/cost-log.md").read_text()
        self.assertIn("hello | 150 | 0 | 300 | 4 | 2", log)
        run("report", "hello", ws=self.ws)
        self.assertEqual((self.ws / "product/cost-log.md").read_text().count("hello |"), 1, "cost line appended once")

    def test_every_subtask_lands_in_exactly_one_block(self):
        state = load_state(self.ws, "hello")
        state.update(phase="safety_net", delivered=False)
        state["subtasks"] += [st("st-05", "api", "svc", goal="Archived rows stay hidden by default"),
                              st("st-06", "web", "web", status="running", goal="The toggle shows archived rows")]
        save_state(self.ws, "hello", state)
        text = run("report", "hello", ws=self.ws).stdout
        works, rest = text.split("What didn't land.")
        missed = rest.split("Assumptions I made.")[0]
        for goal in [s["goal"] for s in state["subtasks"]]:
            self.assertEqual((goal in works) + (goal in missed), 1, goal)
        self.assertIn("- Archived rows stay hidden by default: the run stopped before it started", missed)
        self.assertIn("- The toggle shows archived rows: the run stopped while it was under way", missed)
        self.assertNotIn("Everything planned landed", text)
        state["subtasks"] = [s for s in state["subtasks"] if s["status"] == "done"]
        state.update(phase="finished", delivered=True)
        save_state(self.ws, "hello", state)
        text = run("report", "hello", ws=self.ws).stdout
        self.assertIn("What didn't land.\nNothing.\n", text)
        state["subtasks"] = []
        save_state(self.ws, "hello", state)
        text = run("report", "hello", ws=self.ws).stdout
        self.assertIn("What works now.\nNothing landed yet.\n\nWhat didn't land.\nNothing was planned.\n", text)
        with open(self.ws / "product/client.config.yaml", "a") as f:
            f.write("design:\n  comparable: false\n")
        self.assertNotIn("pixel for pixel", run("report", "hello", ws=self.ws).stdout, "a service feature has no design")
        state["kind"] = "mixed"
        save_state(self.ws, "hello", state)
        self.assertIn("- The design cannot be compared pixel for pixel, as the config declares, so no visual check ran.", run("report", "hello", ws=self.ws).stdout)

    def test_an_assumption_carrying_code_or_a_path_is_refused(self):
        gaps = self.ws / "product/features/hello/spec-gaps.md"
        good = gaps.read_text()
        for assumed, problem in [("`archived=1` only", "which is code or a path"),
                                 ("the class lives in public/style.css", "which is code or a path"),
                                 ("a button whose text swaps " + "x" * 160, "past 160")]:
            gaps.write_text("# gaps\n\n## Which format wins?\nAssumed: %s\nAffects: st-01\nPinned: st-01 lint\n" % assumed)
            done = run("report", "hello", ws=self.ws)
            self.assertEqual(done.returncode, 1, assumed)
            self.assertIn("'Assumed:' is one plain line", done.stderr)
            self.assertIn(problem, done.stderr, assumed)
            self.assertIn("Put the reasoning in the lines below it", done.stderr)
        gaps.write_text("# gaps\n\n## Which format wins?\nAssumed: commas, the common case.\nAffects: st-01\nPinned: st-01 lint\nThe spec named neither; both readers accept commas.\n")
        text = run("report", "hello", ws=self.ws).stdout
        self.assertIn("- commas, the common case.", text)
        self.assertNotIn("both readers accept", text, "the reasoning stays in the gaps file")
        gaps.write_text(good)

    def plan_of(self, n, tokens_each):
        state = load_state(self.ws, "hello")
        state["subtasks"] = [st("st-%02d" % i, "api", "svc", status="done", attempts=1, commit="a" * 40, goal="Step %d" % i,
                                cost=dict(COST, tokens_in=tokens_each - 1000, tokens_out=1000)) for i in range(1, n + 1)]
        save_state(self.ws, "hello", state)
        return run("report", "hello", ws=self.ws).stdout

    def test_the_overrun_is_counted_once_over_the_run_and_never_per_subtask(self):
        # The config budgets 40,000 per run plus 6,000 per sub-task: ten sub-tasks at 10,000 each is the budget exactly.
        self.assertNotIn("Over the budget", self.plan_of(10, 10000))
        self.assertEqual(self.plan_of(11, 10000).count("Over the budget"), 1, "one run, one overrun line")

    def test_the_budget_follows_the_plan_and_not_the_run_it_was_measured_on(self):
        # A two-sub-task run at budget costs 52,000, so its whole-run rate is 26,000 a sub-task. Held against that run's
        # total, a fifteen-sub-task plan spending the same per sub-task passes; held against the plan, it does not.
        self.assertNotIn("Over the budget", self.plan_of(2, 26000))
        text = self.plan_of(15, 26000)
        self.assertIn("Over the budget of 130000 tokens for 15 sub-tasks", text)

    def test_a_detail_path_is_written_from_the_workspace_root(self):
        state = load_state(self.ws, "hello")
        ask = dict(ASK, detail=str(self.ws / "product/features/hello"))
        state["subtasks"][3]["ask"] = ask
        save_state(self.ws, "hello", state)
        text = run("report", "hello", ws=self.ws).stdout
        self.assertNotIn(str(self.ws), text, "no absolute path anywhere in the report")
        self.assertTrue(text.rstrip().endswith("product/features/hello/gaps/"))
        notified = run("ask", "hello", "st-04", ws=self.ws)
        self.assertEqual(notified.returncode, 0, notified.stderr)

    def test_partial_when_not_delivered_and_median_after_three_runs(self):
        state = load_state(self.ws, "hello")
        state["delivered"] = False
        save_state(self.ws, "hello", state)
        with open(self.ws / "product/cost-log.md", "a") as f:
            f.write("a | 100 | 10 | 1 | 0\nb | 300 | 30 | 1 | 0\nc | 200 | 20 | 1 | 0\n")
        text = run("report", "hello", ws=self.ws).stdout
        self.assertTrue(text.startswith("hello — partial\n"))
        self.assertIn("Last three runs: median 200 tokens, 20 s wall time.", text)
        self.assertIn("was not delivered", text)

    def test_notify_pushes_run_finished_and_never_blocks(self):
        server = HTTPServer(("127.0.0.1", 0), Inbox)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        url = "http://127.0.0.1:%d/" % server.server_port
        env = {"HARNESS_WORKSPACE": str(self.ws), "HARNESS_TELEGRAM_URL": url, "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}
        (self.ws / "secrets/telegram_chat_id").write_text("4242\n")
        done = subprocess.run([str(BIN / "notify"), "hello", "run_finished"], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("run_finished sent", done.stdout)
        self.assertEqual(len(Inbox.received), 1)
        self.assertEqual(Inbox.received[0]["chat_id"], "4242")
        self.assertTrue(Inbox.received[0]["text"].startswith("hello — done with gaps"))
        self.assertEqual(load_state(self.ws, "hello")["frictions"], [])

        env["HARNESS_TELEGRAM_URL"] = "http://127.0.0.1:1/"
        down = subprocess.run([str(BIN / "notify"), "hello", "needs_answer"], env=env, capture_output=True, text=True)
        self.assertEqual(down.returncode, 0, down.stderr)
        self.assertIn("not sent", down.stdout)
        self.assertIn("notify · needs_answer not sent", load_state(self.ws, "hello")["frictions"][0])

        noop = subprocess.run([str(BIN / "notify"), "hello", "subtask_done"], env=env, capture_output=True, text=True)
        self.assertEqual(noop.returncode, 0)
        self.assertIn("is not pushed", noop.stdout)
        self.assertEqual(len(Inbox.received), 1)
