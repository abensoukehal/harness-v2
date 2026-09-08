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


PIN = "product/harness.pin"


def find_workspace(start=None, check=True):
    """The workspace holding cwd (or HARNESS_WORKSPACE). With check, refuse a harness/ that drifted from the pin."""
    override = os.environ.get("HARNESS_WORKSPACE")
    if override:
        ws = Path(override).resolve()
        if not (ws / "product" / "client.config.yaml").exists():
            raise HarnessError("HARNESS_WORKSPACE=%s has no product/client.config.yaml" % ws)
    else:
        here = Path(start or os.getcwd()).resolve()
        ws = next((d for d in [here, *here.parents] if (d / "product" / "client.config.yaml").exists()), None)
        if ws is None:
            raise HarnessError("not inside a workspace: no product/client.config.yaml above %s" % here)
    if check:
        check_pin(ws)
    return ws


def check_pin(ws):
    """harness/ runs exactly the commit product/harness.pin names, or nothing runs (2.1)."""
    pin = ws / PIN
    if not (ws / "harness" / ".git").exists():
        return
    if not pin.exists():
        raise HarnessError("no %s: run harness/bin/pin to pin the harness commit" % PIN)
    wanted = pin.read_text().strip()
    actual = git("rev-parse", "HEAD", cwd=ws / "harness")
    if actual != wanted:
        raise HarnessError("harness/ is at %s but %s says %s; run harness/bin/pin to move the pin or git -C harness checkout %s"
                           % (actual[:12], PIN, wanted[:12], wanted[:12]))


def git(*args, cwd=None, env=None):
    try:
        done = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)
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
