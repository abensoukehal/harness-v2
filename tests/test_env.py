import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from helpers import MONO_CONFIG, env_config, env_workspace, make_repo, run, sh
from harness import worktree
from harness.config import load_config, load_state, stack_dir
from harness.env import stop_all
from harness.ports import allocate, is_held

SECRET = "hunter2-secret"


class Ports(unittest.TestCase):
    def test_allocate_distinct_and_is_held(self):
        ports = allocate(["a", "b", "c"])
        self.assertEqual(len(set(ports.values())), 3)
        for p in ports.values():
            self.assertFalse(is_held(p))
        with socket.socket() as s:
            s.bind(("127.0.0.1", ports["a"]))
            s.listen()
            self.assertTrue(is_held(ports["a"]))


class Worktrees(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_one_per_repo_idempotent_remove_keeps_branch(self):
        ws = env_workspace(self.root)
        cfg, state = load_config(ws), load_state(ws, "hello")
        worktree.ensure(ws, cfg, "hello", state)
        worktree.ensure(ws, cfg, "hello", state)
        self.assertEqual(state["worktrees"], {"svc": ".worktrees/hello/svc", "web": ".worktrees/hello/web"})
        self.assertEqual(state["branch"], "feature/hello")
        for repo in ["svc", "web"]:
            self.assertEqual(sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=ws / ".worktrees/hello" / repo), "feature/hello")
        worktree.remove(ws, cfg, "hello", state)
        self.assertFalse((ws / ".worktrees/hello").exists())
        self.assertEqual(state["worktrees"], {})
        self.assertIn("feature/hello", sh("git", "branch", "--list", "feature/hello", cwd=ws / "repos/svc"))
        worktree.ensure(ws, cfg, "hello", state)  # branch exists now: reused, not recreated
        self.assertTrue((ws / ".worktrees/hello/web/README").exists())

    def test_monorepo_gets_one_worktree(self):
        ws = env_workspace(self.root, config=MONO_CONFIG, repos=("mono",))
        cfg, state = load_config(ws), load_state(ws, "hello")
        worktree.ensure(ws, cfg, "hello", state)
        self.assertEqual(state["worktrees"], {"mono": ".worktrees/hello/mono"})
        self.assertEqual(stack_dir(ws, cfg, "hello", "a"), ws / ".worktrees/hello/mono/apps/a")


class Up(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def workspace(self, **kw):
        ws = env_workspace(self.root, config=env_config(**kw))
        self.addCleanup(stop_all, ws, "hello")
        return ws

    def test_up_orders_stacks_seeds_and_scrubs_then_cleanup_and_close(self):
        ws = self.workspace()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        state = load_state(ws, "hello")
        self.assertEqual(set(state["ports"]), {"api", "web"})
        self.assertEqual(set(state["worktrees"]), {"svc", "web"})
        for name in ["api", "web"]:
            self.assertTrue((ws / ".run/hello" / (name + ".pid")).exists())
            self.assertIn("%s: port %d healthy" % (name, state["ports"][name]), done.stdout)
        self.assertTrue(is_held(state["ports"]["api"]))
        self.assertTrue((ws / ".worktrees/hello/svc/seed.marker").exists())
        log = (ws / ".run/hello/web.log").read_text()
        self.assertIn("[REDACTED DB_PASSWORD]", log)
        self.assertNotIn(SECRET, log)
        self.assertNotIn(SECRET, done.stdout + done.stderr)

        cleaned = run("cleanup", "hello", ws=ws)
        self.assertEqual(cleaned.returncode, 0, cleaned.stderr)
        self.assertFalse((ws / ".run/hello").exists())
        for port in state["ports"].values():
            self.assertFalse(is_held(port))
        self.assertEqual(load_state(ws, "hello")["ports"], {})
        self.assertTrue((ws / ".worktrees/hello/svc").exists())
        self.assertEqual(run("cleanup", "hello", ws=ws).returncode, 0)

        self.assertEqual(run("close", "hello", ws=ws).returncode, 0)
        self.assertFalse((ws / ".worktrees/hello").exists())
        self.assertEqual(load_state(ws, "hello")["worktrees"], {})

    def test_never_healthy_fails_at_environment_step(self):
        ws = self.workspace(web_health='log: "will not appear"', web_timeout=2)
        t0 = time.monotonic()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertIn("stack web not healthy after 2s", done.stderr)
        self.assertNotIn(SECRET, done.stdout + done.stderr)
        self.assertFalse((ws / ".run/hello").exists())
        self.assertFalse(is_held(load_state(ws, "hello")["ports"]["api"]), "api was left running")

    def test_dies_at_boot_fails_immediately(self):
        ws = self.workspace(web_dev="echo boom; exit 3", web_timeout=15)
        t0 = time.monotonic()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertLess(time.monotonic() - t0, 8)
        self.assertIn("stack web exited with code 3", done.stderr)
        self.assertIn("boom", done.stderr)

    def test_seed_failure_fails_the_run(self):
        ws = self.workspace(api_seed="echo no fixtures; false")
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("stack api: seed failed", done.stderr)
        self.assertIn("no fixtures", done.stderr)
        self.assertFalse((ws / ".run/hello").exists())
        self.assertFalse(is_held(load_state(ws, "hello")["ports"]["api"]))

    def test_missing_state_or_secret_is_named(self):
        ws = self.workspace()
        (ws / "secrets/web.env").unlink()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("secrets/web.env is missing", done.stderr)
        (ws / "product/features/hello/state.json").unlink()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("/harness-plan hello", done.stderr)


if __name__ == "__main__":
    unittest.main()
