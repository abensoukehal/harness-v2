"""The safety net freeze (phase 3 exit) and the check every later launch runs (4.1)."""
import subprocess

from . import HarnessError, git
from .config import load_state, save_state

IDENTITY = ["-c", "user.name=harness", "-c", "user.email=harness@localhost"]


def freeze(ws, slug):
    product = ws / "product"
    if not (product / ".git").exists():
        raise HarnessError("product/ is not a git repository; the net cannot be frozen")
    git("add", "-A", "tests", cwd=product)
    if git("status", "--porcelain", "tests", cwd=product):
        git(*IDENTITY, "commit", "-q", "-m", "Freeze safety net for %s" % slug, cwd=product)
    elif subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=product, capture_output=True).returncode:
        git(*IDENTITY, "commit", "-q", "--allow-empty", "-m", "Freeze safety net for %s" % slug, cwd=product)
    sha = git("rev-parse", "HEAD", cwd=product)
    state = load_state(ws, slug)
    state["net_commit"] = sha
    save_state(ws, slug, state)
    return sha


def check(ws, slug):
    """Refuse when product/tests differs from the frozen net, or when nothing was frozen and sub-tasks exist."""
    state = load_state(ws, slug)
    sha = state.get("net_commit")
    if not sha:
        if state["subtasks"]:
            raise HarnessError("safety net is not frozen: no net_commit in state for %s; run harness/bin/net freeze %s at the end of phase 3" % (slug, slug))
        return None
    product = ws / "product"
    changed = git("diff", "--name-only", sha, "--", "tests", cwd=product).split()
    untracked = [line[3:] for line in git("status", "--porcelain", "--untracked-files=all", "tests", cwd=product).splitlines() if line.startswith("??")]
    files = sorted(set(changed) | set(untracked))
    if files:
        raise HarnessError("product/tests differs from the frozen safety net %s:\n  %s\nRestore it or refreeze deliberately" % (sha[:12], "\n  ".join(files)))
    return sha
