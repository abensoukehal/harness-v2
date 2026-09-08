"""The retro's own engine clone (14.5): it edits, tests, commits and pushes there, and the workspace's harness/ never moves off the pin."""
import shutil
import subprocess
import sys

from . import HarnessError, git
from .workspace import install_harness


def retro_tree(ws, slug, out=sys.stdout):
    harness = ws / "harness"
    if not (harness / ".git").exists():
        raise HarnessError("%s has no harness checkout" % ws)
    tree = ws / ".retro" / slug
    shutil.rmtree(tree, ignore_errors=True)
    tree.parent.mkdir(exist_ok=True)
    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=harness, capture_output=True, text=True)
    url = origin.stdout.strip() if origin.returncode == 0 else None
    fresh = bool(url) and subprocess.run(["git", "clone", "-q", url, str(tree)], capture_output=True).returncode == 0
    if not fresh:
        shutil.rmtree(tree, ignore_errors=True)
        git("clone", "-q", str(harness), str(tree))
        if url:
            git("remote", "set-url", "origin", url, cwd=tree)
        out.write("harness remote %s unreachable: cloned harness/ at the pin instead\n" % (url or "unset"))
    install_harness(tree)
    out.write("%s\n" % tree)
    return tree
