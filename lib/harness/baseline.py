"""The inherited baseline (phase 3): the client's own suite on the untouched base, failing tests recorded by name."""
import os
import re
import subprocess
import sys

from . import HarnessError, worktree
from .config import load_config, load_state, save_state, stack_dir
from .env import kill_group, load_secrets, run_dir, spawn, tail

TIMEOUT_S = 600
DURATION = r"(?: \(\d+(?:\.\d+)? ?m?s\))?"
# One line per failing test, as the common runners print it: pytest, TAP (node --test), jest and vitest, playwright, go test.
FAILED = [re.compile(r"^FAILED (\S+)"), re.compile(r"^\s*not ok \d+ - (.+?)(?: # .*)?$"), re.compile(r"^\s*[✕✘✖×] (.+?)%s$" % DURATION),
          re.compile(r"^\s*\d+\) .*› (.+?)(?: ─+)?$"), re.compile(r"^--- FAIL: (\S+)")]
# The runner's own summary headings, which name no test.
HEADINGS = re.compile(r"^(failing tests|failures|errors|test failures|short test summary info|summary)\b|:$", re.I)
# A suite that never ran: the runner itself failed to load or start.
BROKEN = re.compile(r"MODULE_NOT_FOUND|Cannot find module|ModuleNotFoundError|ImportError|command not found|"
                    r"No such file or directory|file or directory not found|unknown command|no tests ran|error: unknown option", re.I)
PASSED = [re.compile(r"^\s*ℹ pass (\d+)", re.M), re.compile(r"(\d+) passed"), re.compile(r"(\d+) passing"), re.compile(r"(\d+) tests? ok")]


def failing_tests(output):
    names = []
    for line in output.splitlines():
        for rx in FAILED:
            m = rx.match(line)
            if m:
                name = m.group(1).strip()
                if name and not HEADINGS.search(name):
                    names.append(name)
                break
    return list(dict.fromkeys(names))


def passes(output):
    """How many of the client's tests passed, or None when the runner says nothing."""
    for rx in PASSED:
        m = rx.search(output)
        if m:
            return int(m.group(1))
    return None


def did_not_run(output, code, names):
    """Why this suite produced no baseline at all, or None when it ran (phase 3)."""
    hit = BROKEN.search(output)
    if hit and not passes(output):
        line = next((l.strip() for l in output.splitlines() if hit.re.search(l)), hit.group(0))
        return "the runner did not start: %s" % line[:160]
    if code and not names:
        return "exited %d and named no failing test" % code
    return None


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
        output = scrubber.scrub(logfile.read_text(errors="replace")) if logfile.exists() else ""
        names = failing_tests(output)
        why = did_not_run(output, code, names)
        if why:
            # No baseline means QA cannot tell the client's red from ours, so the run stops here (phase 3).
            state["frictions"].append("baseline · %s suite did not run · environment · %s" % (name, why))
            save_state(ws, slug, state)
            raise HarnessError("stack %s: no baseline, %s\nFix the client_tests command for %s, then rerun the build." % (name, why, name))
        recorded[name] = names
        out.write("%s: %d failing at the start%s\n" % (name, len(names), (": " + ", ".join(names)) if names else ""))
    state["client_test_baseline"] = recorded
    save_state(ws, slug, state)
    return recorded
