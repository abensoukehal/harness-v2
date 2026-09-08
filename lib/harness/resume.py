"""Resume a run from state.json, trusting git and the OS over the file (8.3)."""
import subprocess
import sys

from . import git, worktree
from .config import load_config, load_state, save_state
from .env import up
from .ports import is_held

MAX_INTERRUPTIONS = 3


def on_branch(wt, sha):
    if not sha:
        return False
    exists = subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], cwd=wt, capture_output=True).returncode == 0
    return exists and subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"], cwd=wt, capture_output=True).returncode == 0


def reconcile(ws, cfg, slug, state):
    """Apply reality to state. Returns the corrections made, one line each."""
    notes = []
    for st in state["subtasks"]:
        wt = ws / st["worktree"]
        if st["status"] == "done" and not on_branch(wt, st.get("commit")):
            notes.append("%s: marked done but commit %s is not on %s; reset to pending" % (st["id"], st.get("commit"), state["branch"]))
            state["frictions"].append("%s · state said done but the commit was not on the branch · resume" % st["id"])
            st["status"] = "pending"
            st.pop("commit", None)
        elif st["status"] == "running":
            git("checkout", "--", ".", cwd=wt)
            git("clean", "-fdq", cwd=wt)
            st["interruptions"] = st.get("interruptions", 0) + 1
            if st["interruptions"] >= MAX_INTERRUPTIONS:
                st["status"], st["reason"] = "blocked", "unstable"
                notes.append("%s: interrupted %d times; blocked as unstable" % (st["id"], st["interruptions"]))
            else:
                st["status"] = "pending"
                notes.append("%s: interrupted; partial work dropped, back to pending" % st["id"])
    held = [name for name, port in state["ports"].items() if is_held(port)]
    if held:
        notes.append("ports still held for %s; stacks restart on fresh ports" % ", ".join(held))
    if state["phase"] in ("build", "qa"):
        state["phase"] = "safety_net"
        notes.append("phase: safety net reruns before build continues")
    return notes


def resume(ws, slug, out=sys.stdout):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    worktree.ensure(ws, cfg, slug, state)
    notes = reconcile(ws, cfg, slug, state)
    save_state(ws, slug, state)
    up(ws, slug, out)
    for note in notes:
        out.write(note + "\n")
    return notes
