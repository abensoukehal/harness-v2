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
        (self.ws / "product/features/hello/spec-gaps.md").write_text("# gaps\n\n## Which format wins?\nAssumed: comma, the common case.\nAffects: st-01\n\n## Empty export?\nAssumed: a header row and nothing else.\nAffects: st-01\n")
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
                     "- Each row carries a summary: it needs an answer, below", "A. Comma separated (recommended)", "- Which format wins? comma, the common case.", "- Empty export? a header row and nothing else.",
                     "150 tokens, 300 s wall time, 4 sub-tasks, 5 attempts, 2 blocked.", "No three earlier runs to compare against.",
                     "Answer the question above first.", "Open a PR from feature/hello."]:
            self.assertIn(line, text, line)
        for absent in ["repos/", "assert 3 == 2", "st-0"]:
            self.assertNotIn(absent, text.split("Detail:")[0], absent)
        self.assertEqual(text.count("Detail:"), 1)
        log = (self.ws / "product/cost-log.md").read_text()
        self.assertIn("hello | 150 | 300 | 4 | 2", log)
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
