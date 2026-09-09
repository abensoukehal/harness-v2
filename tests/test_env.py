import json
import socket
import tempfile
import time
import unittest
from pathlib import Path

from helpers import MONO_CONFIG, env_config, env_workspace, make_repo, run, sh
from harness import worktree
from harness.config import create_state, load_config, load_state, save_state, stack_dir
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
        self.assertEqual(set(state["ports"]), {"api", "web", "db"})
        self.assertEqual(set(state["worktrees"]), {"svc", "web"})
        self.assertTrue(is_held(state["ports"]["db"]), "db (repo-less stack) listens")
        for name in ["api", "web"]:
            self.assertTrue((ws / ".run/hello" / (name + ".pid")).exists())
            self.assertIn("%s: port %d healthy" % (name, state["ports"][name]), done.stdout)
        self.assertTrue(is_held(state["ports"]["api"]))
        self.assertTrue((ws / ".worktrees/hello/svc/seed.marker").exists())
        self.assertEqual((ws / ".worktrees/hello/svc/install.marker").read_text(), "installed\n", "install ran when the worktree was created")
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
        self.assertEqual(run("up", "hello", ws=ws).returncode, 0)
        self.assertEqual((ws / ".worktrees/hello/svc/install.marker").read_text(), "installed\n", "install runs once per worktree, not per up")
        self.assertEqual(run("cleanup", "hello", ws=ws).returncode, 0)

        self.assertEqual(run("close", "hello", ws=ws).returncode, 0)
        self.assertFalse((ws / ".worktrees/hello").exists())
        self.assertEqual(load_state(ws, "hello")["worktrees"], {})

    def test_restart_keeps_the_port_and_takes_dependents_along(self):
        ws = self.workspace()
        self.assertEqual(run("up", "hello", ws=ws).returncode, 0)
        ports = load_state(ws, "hello")["ports"]
        pids = {n: (ws / ".run/hello" / (n + ".pid")).read_text() for n in ["api", "web", "db"]}
        (ws / ".run/hello/web.log").write_text("OLD BOOT LINE\n" + (ws / ".run/hello/web.log").read_text())
        done = run("restart", "hello", "web", ws=ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("web: port %d healthy" % ports["web"], done.stdout)
        self.assertNotIn("api:", done.stdout)
        self.assertNotEqual((ws / ".run/hello/web.pid").read_text(), pids["web"])
        self.assertEqual((ws / ".run/hello/api.pid").read_text(), pids["api"])
        self.assertEqual(load_state(ws, "hello")["ports"], ports)
        self.assertNotIn("OLD BOOT LINE", (ws / ".run/hello/web.log").read_text())
        self.assertIn("[REDACTED DB_PASSWORD]", (ws / ".run/hello/web.log").read_text())

        state = load_state(ws, "hello")
        state["subtasks"] = [{"id": "st-01", "stack": "api", "status": "running", "attempts": 2, "interruptions": 0,
                              "worktree": ".worktrees/hello/svc", "exit_criteria": [{"kind": "lint"}]}]
        save_state(ws, "hello", state)
        svc = ws / ".worktrees/hello/svc"
        self.assertEqual((svc / "seed.marker").read_text().count("seeded"), 1)
        (svc / "worker-data.txt").write_text("built up during the sub-task\n")
        done = run("restart", "hello", "api", "--subtask", "st-01", ws=ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("api: port %d healthy" % ports["api"], done.stdout)
        self.assertIn("web: port %d healthy" % ports["web"], done.stdout, "web depends on api and restarts with it")
        self.assertNotIn("db:", done.stdout)
        self.assertNotIn("reseeded", done.stdout)
        self.assertTrue(is_held(ports["api"]))
        self.assertEqual((svc / "seed.marker").read_text().count("seeded"), 1, "a restart does not reseed")
        self.assertEqual((svc / "worker-data.txt").read_text(), "built up during the sub-task\n")
        state = load_state(ws, "hello")
        self.assertEqual(state["subtasks"][0]["attempts"], 2, "a restart spends no attempt")
        self.assertNotIn("reseeds", state)
        done = run("restart", "hello", "api", "--reseed", "--subtask", "st-01", ws=ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("api: port %d healthy (reseeded)" % ports["api"], done.stdout)
        self.assertEqual((svc / "seed.marker").read_text().count("seeded"), 2)
        self.assertEqual(load_state(ws, "hello")["reseeds"], [{"stack": "api", "subtask": "st-01"}, {"stack": "web", "subtask": "st-01"}])
        unknown = run("restart", "hello", "cache", ws=ws)
        self.assertEqual(unknown.returncode, 1)
        self.assertIn("unknown stack cache", unknown.stderr)
        run("cleanup", "hello", ws=ws)
        down = run("restart", "hello", "web", ws=ws)
        self.assertEqual(down.returncode, 1)
        self.assertIn("is not up", down.stderr)

    def test_never_healthy_fails_at_environment_step(self):
        ws = self.workspace(web_health='log: "will not appear"', web_timeout=2)
        state = load_state(ws, "hello")
        state["subtasks"] = [{"id": "st-01", "stack": "api", "status": "pending", "attempts": 0, "interruptions": 0,
                              "worktree": ".worktrees/hello/svc", "exit_criteria": [{"kind": "lint"}]}]
        save_state(ws, "hello", state)
        t0 = time.monotonic()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertLess(time.monotonic() - t0, 10)
        self.assertIn("stack web not healthy after 2s", done.stderr)
        self.assertEqual([s["status"] for s in load_state(ws, "hello")["subtasks"]], ["pending"], "no sub-task started")
        self.assertNotIn(SECRET, done.stdout + done.stderr)
        self.assertFalse((ws / ".run/hello").exists())
        self.assertFalse(is_held(load_state(ws, "hello")["ports"]["api"]), "api was left running")

    def test_two_features_at_once_get_separate_worktrees_and_ports(self):
        ws = self.workspace()
        self.assertEqual(run("new", "world", ws=ws).returncode, 0)
        create_state(ws, "world", "service")
        self.addCleanup(stop_all, ws, "world")
        for slug in ["hello", "world"]:
            done = run("up", slug, ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
        hello, world = load_state(ws, "hello"), load_state(ws, "world")
        self.assertEqual(set(hello["ports"].values()) & set(world["ports"].values()), set())
        for st in (hello, world):
            self.assertTrue(is_held(st["ports"]["api"]))
        self.assertEqual(hello["worktrees"], {"svc": ".worktrees/hello/svc", "web": ".worktrees/hello/web"})
        self.assertEqual(world["worktrees"], {"svc": ".worktrees/world/svc", "web": ".worktrees/world/web"})
        self.assertEqual(sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=ws / ".worktrees/world/svc"), "feature/world")
        self.assertEqual(sh("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=ws / ".worktrees/hello/svc"), "feature/hello")
        self.assertEqual(run("cleanup", "hello", ws=ws).returncode, 0)
        self.assertFalse(is_held(hello["ports"]["api"]))
        self.assertTrue(is_held(world["ports"]["api"]), "the other feature keeps running")
        self.assertEqual(run("cleanup", "world", ws=ws).returncode, 0)
        self.assertFalse(is_held(world["ports"]["api"]))

    def test_dies_at_boot_fails_immediately(self):
        ws = self.workspace(web_dev="echo boom; exit 3", web_timeout=15)
        t0 = time.monotonic()
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertLess(time.monotonic() - t0, 8)
        self.assertIn("stack web exited with code 3", done.stderr)
        self.assertIn("boom", done.stderr)

    def test_install_failure_fails_at_the_environment_step(self):
        ws = self.workspace(api_install="echo no lockfile; exit 2")
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("stack api: install failed with code 2", done.stderr)
        self.assertIn("no lockfile", done.stderr)
        self.assertFalse((ws / ".run/hello").exists())

    def test_seed_failure_fails_the_run(self):
        ws = self.workspace(api_seed="echo no fixtures; false")
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("stack api: seed failed", done.stderr)
        self.assertIn("no fixtures", done.stderr)
        self.assertFalse((ws / ".run/hello").exists())
        self.assertFalse(is_held(load_state(ws, "hello")["ports"]["api"]))

    def test_a_secret_under_the_floor_is_refused_by_key(self):
        ws = self.workspace()
        (ws / "secrets/api.env").write_text("API_KEY=abcd\n")
        done = run("up", "hello", ws=ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("secrets: API_KEY under the 8-character floor", done.stderr)
        self.assertNotIn("DB_PASSWORD", done.stderr, "only the value that is too short is named")
        self.assertFalse((ws / ".run/hello").exists(), "nothing started behind a scrubber that cannot cover a value")

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
