"""Mechanical layer of the harness: workspaces, ports, worktrees, environment, secrets."""
import os
import re
import subprocess
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
SLUG = re.compile(r"^[a-z0-9-]+$")


class HarnessError(Exception):
    """A failure the user must see. The message is the whole report."""


def find_workspace(start=None):
    override = os.environ.get("HARNESS_WORKSPACE")
    if override:
        ws = Path(override).resolve()
        if not (ws / "product" / "client.config.yaml").exists():
            raise HarnessError("HARNESS_WORKSPACE=%s has no product/client.config.yaml" % ws)
        return ws
    here = Path(start or os.getcwd()).resolve()
    for d in [here, *here.parents]:
        if (d / "product" / "client.config.yaml").exists():
            return d
    raise HarnessError("not inside a workspace: no product/client.config.yaml above %s" % here)


def git(*args, cwd=None):
    try:
        done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        raise HarnessError("git %s: %s" % (" ".join(args), e.stderr.strip()))
    return done.stdout.strip()


def check_slug(value, what="slug"):
    if not SLUG.match(value or ""):
        raise HarnessError("%s %r must match %s" % (what, value, SLUG.pattern))
    return value


def main(fn):
    """Entry point for bin scripts: run fn(argv), print HarnessError to stderr, exit 1."""
    try:
        fn(sys.argv[1:])
    except HarnessError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
