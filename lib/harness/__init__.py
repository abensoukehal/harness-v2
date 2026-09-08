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


def find_workspace(check=True):
    """The workspace root, from HARNESS_WORKSPACE only. Never the working directory (2.2). bin scripts also take --workspace DIR."""
    override = os.environ.get("HARNESS_WORKSPACE")
    if not override:
        raise HarnessError("no workspace: pass --workspace DIR or set HARNESS_WORKSPACE; harness/bin/link writes it into .claude/settings.json")
    ws = Path(override).resolve()
    if not (ws / "product" / "client.config.yaml").exists():
        raise HarnessError("workspace %s has no product/client.config.yaml" % ws)
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
    """Entry point for bin scripts: --workspace DIR sets HARNESS_WORKSPACE, then fn(argv); a HarnessError goes to stderr, exit 1."""
    argv = sys.argv[1:]
    try:
        if "--workspace" in argv:
            i = argv.index("--workspace")
            if i + 1 >= len(argv):
                raise HarnessError("--workspace needs a directory")
            os.environ["HARNESS_WORKSPACE"] = argv[i + 1]
            del argv[i:i + 2]
        fn(argv)
    except HarnessError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
