import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import env_config, env_workspace, sh
from harness import worktree
from harness.config import load_config, load_state, save_state


def push(wt, *args):
    return subprocess.run(["git", "push", "-q", *args], cwd=str(wt), capture_output=True, text=True)


class PrePush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        self.remote = Path(self.tmp.name) / "remote.git"
        sh("git", "init", "-q", "--bare", str(self.remote), cwd=self.tmp.name)
        repo = self.ws / "repos/svc"
        sh("git", "remote", "add", "origin", str(self.remote), cwd=repo)
        sh("git", "push", "-q", "-u", "origin", "main", cwd=repo)
        self.state = load_state(self.ws, "hello")
        worktree.ensure(self.ws, load_config(self.ws), "hello", self.state)
        save_state(self.ws, "hello", self.state)
        self.wt = self.ws / ".worktrees/hello/svc"
        (self.wt / "f.py").write_text("1\n")
        sh("git", "add", ".", cwd=self.wt)
        sh("git", "commit", "-q", "-m", "Add f", cwd=self.wt)

    def remote_main(self):
        return sh("git", "rev-parse", "main", cwd=self.remote)

    def test_feature_branch_only_no_force_no_delete(self):
        main_before = self.remote_main()
        ok = push(self.wt, "origin", "feature/hello")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(sh("git", "rev-parse", "feature/hello", cwd=self.remote), sh("git", "rev-parse", "HEAD", cwd=self.wt))

        to_main = push(self.wt, "origin", "HEAD:main")
        self.assertEqual(to_main.returncode, 1)
        self.assertIn("refused refs/heads/main", to_main.stderr)
        self.assertEqual(self.remote_main(), main_before)

        sh("git", "commit", "-q", "--amend", "-m", "Add f again", cwd=self.wt)
        forced = push(self.wt, "--force", "origin", "feature/hello")
        self.assertEqual(forced.returncode, 1)
        self.assertIn("refused force-push", forced.stderr)
        leased = push(self.wt, "--force-with-lease", "origin", "feature/hello")
        self.assertEqual(leased.returncode, 1)

        deleted = push(self.wt, "origin", ":feature/hello")
        self.assertEqual(deleted.returncode, 1)
        self.assertIn("refused deleting", deleted.stderr)
        self.assertEqual(sh("git", "branch", "--list", "feature/hello", cwd=self.remote).strip(), "feature/hello")

    def test_direct_merge_reaches_target_only_at_delivery(self):
        (self.ws / "product/client.config.yaml").write_text(env_config().replace("mode: branch", "mode: direct_merge"))
        self.state["phase"] = "build"
        save_state(self.ws, "hello", self.state)
        early = push(self.wt, "origin", "HEAD:main")
        self.assertEqual(early.returncode, 1)
        self.assertIn("refused refs/heads/main", early.stderr)

        self.state["phase"] = "delivery"
        save_state(self.ws, "hello", self.state)
        delivered = push(self.wt, "origin", "HEAD:main")
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        self.assertEqual(self.remote_main(), sh("git", "rev-parse", "HEAD", cwd=self.wt))

    def test_direct_merge_reads_the_target_of_this_worktree_repo(self):
        # A branch map: svc merges into main, web into trunk. The hook must resolve the repo it runs in, not the map.
        config = env_config().replace("mode: branch", "mode: direct_merge")
        config = config.replace("target_branch: main", "target_branch: {svc: main, web: trunk}")
        (self.ws / "product/client.config.yaml").write_text(config)
        self.state["phase"] = "delivery"
        save_state(self.ws, "hello", self.state)
        to_trunk = push(self.wt, "origin", "HEAD:trunk")
        self.assertEqual(to_trunk.returncode, 1)
        self.assertIn("refused refs/heads/trunk", to_trunk.stderr, "trunk is web's target, not svc's")
        delivered = push(self.wt, "origin", "HEAD:main")
        self.assertEqual(delivered.returncode, 0, delivered.stderr)
        self.assertEqual(self.remote_main(), sh("git", "rev-parse", "HEAD", cwd=self.wt))

    def test_plain_checkout_is_not_governed(self):
        repo = self.ws / "repos/svc"
        (repo / "g.py").write_text("2\n")
        sh("git", "add", ".", cwd=repo)
        sh("git", "commit", "-q", "-m", "Add g", cwd=repo)
        self.assertEqual(push(repo, "origin", "main").returncode, 0)
