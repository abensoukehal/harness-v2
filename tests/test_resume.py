import socket
import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run, sh
from harness import worktree
from harness.config import load_config, load_state, save_state
from harness.env import stop_all
from harness.ports import is_held

FAKE_SHA = "0123456789abcdef" * 2 + "01234567"
COST = {"cost": {"tokens_in": 10, "tokens_out": 5, "duration_s": 3, "lines_added": 2}, "attempts": 1, "interruptions": 0}
CRIT = [{"kind": "lint"}]
API = dict(worktree=".worktrees/hello/svc", exit_criteria=CRIT)
WEB = dict(worktree=".worktrees/hello/web", exit_criteria=CRIT)


class Resume(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        self.addCleanup(stop_all, self.ws, "hello")
        cfg, state = load_config(self.ws), load_state(self.ws, "hello")
        worktree.ensure(self.ws, cfg, "hello", state)
        svc = self.ws / ".worktrees/hello/svc"
        (svc / "real.py").write_text("1\n")
        sh("git", "add", ".", cwd=svc)
        sh("git", "commit", "-q", "-m", "Add real", cwd=svc)
        self.real = sh("git", "rev-parse", "HEAD", cwd=svc)
        repo = self.ws / "repos/svc"
        sh("git", "checkout", "-q", "-b", "other", cwd=repo)
        (repo / "other.py").write_text("2\n")
        sh("git", "add", ".", cwd=repo)
        sh("git", "commit", "-q", "-m", "Add other", cwd=repo)
        self.other = sh("git", "rev-parse", "HEAD", cwd=repo)
        sh("git", "checkout", "-q", "main", cwd=repo)
        state["phase"] = "build"
        state["subtasks"] = [
            dict(id="st-01", stack="api", status="done", commit=self.real, **COST, **API),
            dict(id="st-02", stack="api", status="done", commit=FAKE_SHA, **COST, **API),
            dict(id="st-03", stack="web", status="running", attempts=2, interruptions=0, **WEB),
            dict(id="st-04", stack="api", status="done", commit=self.other, **COST, **API),
            dict(id="st-05", stack="api", status="skipped", reason="runtime", attempts=0, interruptions=0, **API),
            dict(id="st-06", stack="api", status="skipped", reason="depends on st-05", attempts=0, interruptions=0, **API),
        ]
        save_state(self.ws, "hello", state)
        self.web = self.ws / ".worktrees/hello/web"
        (self.web / "README").write_text("changed\n")
        (self.web / "junk.txt").write_text("partial\n")

    def by_id(self):
        return {s["id"]: s for s in load_state(self.ws, "hello")["subtasks"]}

    def test_reality_wins_and_environment_restarts(self):
        done = run("resume", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        st = self.by_id()
        self.assertEqual(st["st-01"]["status"], "done")
        self.assertEqual(st["st-02"]["status"], "pending")
        self.assertNotIn("commit", st["st-02"])
        self.assertEqual(st["st-04"]["status"], "pending")
        self.assertEqual(st["st-03"]["status"], "pending")
        self.assertEqual(st["st-03"]["interruptions"], 1)
        self.assertEqual(st["st-03"]["attempts"], 2)
        self.assertEqual((st["st-05"]["status"], st["st-05"]["attempts"]), ("pending", 0), "a runtime refusal is retried on relaunch, no attempt spent")
        self.assertEqual(st["st-06"]["status"], "pending", "its dependents reopen with it")
        self.assertEqual((self.web / "README").read_text(), "x\n")
        self.assertFalse((self.web / "junk.txt").exists())
        self.assertEqual(sh("git", "status", "--porcelain", cwd=self.web), "")
        state = load_state(self.ws, "hello")
        self.assertEqual(state["phase"], "safety_net")
        self.assertTrue(is_held(state["ports"]["api"]))
        self.assertEqual(len(state["frictions"]), 2)
        for line in ["st-02: marked done", "st-04: marked done", "st-03: interrupted", "st-05: the runtime had refused", "phase: safety net"]:
            self.assertIn(line, done.stdout)

    def test_port_held_by_a_stranger_is_reallocated(self):
        state = load_state(self.ws, "hello")
        state["ports"] = {"api": 50201, "web": 50202, "db": 50203}
        save_state(self.ws, "hello", state)
        with socket.socket() as stranger:
            stranger.bind(("127.0.0.1", 50201))
            stranger.listen()
            done = run("resume", "hello", ws=self.ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("ports still held for api", done.stdout)
            ports = load_state(self.ws, "hello")["ports"]
            self.assertNotEqual(ports["api"], 50201)
            self.assertTrue(is_held(ports["api"]))

    def test_third_interruption_blocks_as_unstable(self):
        state = load_state(self.ws, "hello")
        state["subtasks"][2]["interruptions"] = 2
        save_state(self.ws, "hello", state)
        done = run("resume", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        st = self.by_id()["st-03"]
        self.assertEqual((st["status"], st["reason"], st["interruptions"]), ("blocked", "unstable", 3))
