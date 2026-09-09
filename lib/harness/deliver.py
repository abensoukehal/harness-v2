"""Delivery (10): a run with nothing landed has nothing to push."""
import subprocess
import sys

from . import HarnessError, git
from .config import load_config, load_state, save_state


def refusals(ws, cfg, state):
    """Why this run cannot be delivered, one line each. Empty means it can."""
    why = []
    if not any(s["status"] == "done" for s in state["subtasks"]):
        why.append("no sub-task is done")
    base = cfg["delivery"]["base_branch"]
    empty = []
    for repo, rel in state["worktrees"].items():
        wt = ws / rel
        if not (wt / ".git").exists():
            why.append("no worktree at %s" % rel)
            continue
        if not git("diff", "--name-only", "%s...HEAD" % base, cwd=wt).split():
            empty.append(repo)
    if empty and len(empty) == len(state["worktrees"]):
        why.append("the branch matches %s in %s" % (base, ", ".join(sorted(empty))))
    return why


def deliver(ws, slug, out=sys.stdout):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    why = refusals(ws, cfg, state)
    if why:
        state["delivered"] = False
        state["frictions"].append("delivery · nothing to deliver · " + "; ".join(why))
        save_state(ws, slug, state)
        raise HarnessError("nothing to deliver: %s" % "; ".join(why))
    branch, target = state["branch"], cfg["delivery"]["target_branch"]
    for repo, rel in sorted(state["worktrees"].items()):
        wt = ws / rel
        refs = [branch] + (["%s:%s" % (branch, target)] if cfg["delivery"]["mode"] == "direct_merge" else [])
        for ref in refs:
            done = subprocess.run(["git", "push", "origin", ref], cwd=str(wt), capture_output=True, text=True)
            if done.returncode:
                state["delivered"] = False
                state["frictions"].append("delivery · push of %s refused · %s" % (repo, done.stderr.strip().split("\n")[-1][:160]))
                save_state(ws, slug, state)
                raise HarnessError("push of %s from %s refused:\n%s" % (ref, rel, done.stderr.strip()))
        out.write("%s: %s pushed\n" % (repo, branch))
    state["delivered"] = True
    save_state(ws, slug, state)
    return True
