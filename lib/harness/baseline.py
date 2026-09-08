"""The inherited baseline (phase 3): the client's own suite on the untouched base, failing tests recorded by name."""
import os
import re
import subprocess
import sys

from . import HarnessError, worktree
from .config import load_config, load_state, save_state, stack_dir
from .env import kill_group, load_secrets, run_dir, spawn, tail

TIMEOUT_S = 600
# One line per failing test, as the common runners print it: pytest, TAP (node --test), jest and vitest, playwright, go test.
FAILED = [re.compile(r"^FAILED (\S+)"), re.compile(r"^\s*not ok \d+ - (.+?)(?: # .*)?$"), re.compile(r"^\s*[✕✘✖×] (.+?)(?: \(\d+ ?m?s\))?$"),
          re.compile(r"^\s*\d+\) .*› (.+?)(?: ─+)?$"), re.compile(r"^--- FAIL: (\S+)")]


def failing_tests(output):
    names = []
    for line in output.splitlines():
        for rx in FAILED:
            m = rx.match(line)
            if m:
                names.append(m.group(1).strip())
                break
    return list(dict.fromkeys(names))


def baseline(ws, slug, out=sys.stdout):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    worktree.ensure(ws, cfg, slug, state)
    per_stack, scrubber = load_secrets(ws, cfg)
    rd = run_dir(ws, slug)
    rd.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({"PORT_" + n.upper(): str(p) for n, p in state["ports"].items()})
    recorded = {}
    for name, command in cfg.get("client_tests", {}).items():
        stack_env = dict(env, **per_stack[name])
        logfile = rd / ("baseline-%s.log" % name)
        proc = spawn(command, stack_dir(ws, cfg, slug, name), stack_env, logfile, list(per_stack[name]))
        try:
            code = proc.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            kill_group(proc.pid)
            raise HarnessError("stack %s: the client suite did not finish within %ds" % (name, TIMEOUT_S))
        names = failing_tests(logfile.read_text(errors="replace")) if logfile.exists() else []
        recorded[name] = names
        if code and not names:
            state["frictions"].append("baseline · %s suite exited %d with no test name recognised · %s" % (name, code, tail(logfile, scrubber, 3).replace("\n", " ")[:160]))
        out.write("%s: %d failing at the start%s\n" % (name, len(names), (": " + ", ".join(names)) if names else ""))
    state["client_test_baseline"] = recorded
    save_state(ws, slug, state)
    return recorded
