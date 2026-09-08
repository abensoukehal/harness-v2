"""Bring a feature's stacks up (11, 11.1) and down."""
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import HarnessError
from .config import load_config, load_state, save_state, stack_dir, state_path
from .ports import allocate, is_held
from .secrets import Scrubber, load_env_file
from . import worktree

POLL_S = 0.5
STOP_GRACE_S = 5
SCRUBLOG = Path(__file__).with_name("scrublog.py")


def run_dir(ws, slug):
    return ws / ".run" / slug


def start_order(stacks):
    order, seen = [], set()

    def visit(name):
        if name in seen:
            return
        seen.add(name)
        for dep in stacks[name].get("depends_on", []):
            visit(dep)
        order.append(name)

    for name in sorted(stacks):
        visit(name)
    return order


def load_secrets(ws, cfg):
    per_stack, everything = {}, {}
    for name, stack in cfg["stacks"].items():
        values = {}
        if "env_file" in stack:
            path = ws / "secrets" / stack["env_file"]
            if not path.exists():
                raise HarnessError("stack %s: secrets/%s is missing" % (name, stack["env_file"]))
            values = load_env_file(path)
        per_stack[name] = values
        everything.update(values)
    return per_stack, Scrubber(everything)


def expand(text, env):
    return re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), ""), text)


def piped(command, logfile, keys):
    """Shell line: the command, stdout+stderr through the scrubbing logger into logfile."""
    logger = " ".join(shlex.quote(a) for a in [sys.executable, str(SCRUBLOG), str(logfile), *keys])
    return "{ %s ; } 2>&1 | %s" % (command, logger)


def spawn(command, cwd, env, logfile, keys):
    return subprocess.Popen(
        ["bash", "-o", "pipefail", "-c", piped(command, logfile, keys)],
        cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True)


def tail(path, scrubber, n=10):
    if not path.exists():
        return ""
    lines = path.read_text(errors="replace").splitlines()[-n:]
    return scrubber.scrub("\n".join(lines))


def healthy(health, source, env):
    if "log" in health:
        return source.exists() and re.search(health["log"], source.read_text(errors="replace")) is not None
    try:
        with urllib.request.urlopen(expand(health["http"], env), timeout=2) as r:
            return r.status == health["expect_status"]
    except urllib.error.HTTPError as e:
        return e.code == health["expect_status"]
    except Exception:
        return False


def wait_healthy(name, stack, proc, logfile, cwd, env, scrubber):
    timeout = stack.get("health_timeout_s", 120)
    logs = stack.get("logs", "stdout")
    source = logfile if logs == "stdout" else cwd / logs
    deadline = time.monotonic() + timeout
    while True:
        if healthy(stack["health"], source, env):
            return
        if proc.poll() is not None:
            raise HarnessError("stack %s exited with code %d before becoming healthy\n%s"
                               % (name, proc.returncode, tail(logfile, scrubber)))
        if time.monotonic() > deadline:
            raise HarnessError("stack %s not healthy after %ds\n%s" % (name, timeout, tail(logfile, scrubber)))
        time.sleep(POLL_S)


def seed(name, stack, cwd, env, logfile, keys, scrubber):
    timeout = stack.get("health_timeout_s", 120)
    proc = spawn(stack["seed"], cwd, env, logfile, keys)
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_group(proc.pid)
        raise HarnessError("stack %s: seed did not finish within %ds" % (name, timeout))
    if code:
        raise HarnessError("stack %s: seed failed with code %d\n%s" % (name, code, tail(logfile, scrubber)))


def up(ws, slug, out=sys.stdout):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    worktree.ensure(ws, cfg, slug, state)
    names = list(cfg["stacks"])
    if set(state["ports"]) != set(names) or any(is_held(p) for p in state["ports"].values()):
        state["ports"] = allocate(names)
    save_state(ws, slug, state)
    per_stack, scrubber = load_secrets(ws, cfg)
    stop_all(ws, slug)
    rd = run_dir(ws, slug)
    rd.mkdir(parents=True)
    try:
        for name in start_order(cfg["stacks"]):
            stack = cfg["stacks"][name]
            env = dict(os.environ)
            env.update({"PORT_" + n.upper(): str(p) for n, p in state["ports"].items()})
            env.update(per_stack[name])
            keys = list(per_stack[name])
            cwd = stack_dir(ws, cfg, slug, name)
            if not cwd.is_dir():
                raise HarnessError("stack %s: %s does not exist in the worktree" % (name, cwd.relative_to(ws)))
            logfile = rd / (name + ".log")
            proc = spawn(stack["commands"]["dev"], cwd, env, logfile, keys)
            (rd / (name + ".pid")).write_text(str(proc.pid))
            wait_healthy(name, stack, proc, logfile, cwd, env, scrubber)
            if stack.get("seed"):
                seed(name, stack, cwd, env, logfile, keys, scrubber)
            out.write("%s: port %d healthy\n" % (name, state["ports"][name]))
    except BaseException:
        stop_all(ws, slug)
        raise


def kill_group(pgid, sig=signal.SIGTERM):
    try:
        os.killpg(pgid, sig)
        return True
    except (ProcessLookupError, PermissionError):  # gone, or a zombie the OS reports as EPERM
        return False


def stop_all(ws, slug):
    """Stop every process group the run started, then drop the run directory. No-op when nothing runs."""
    rd = run_dir(ws, slug)
    if not rd.exists():
        return
    groups = [int(p.read_text()) for p in rd.glob("*.pid")]
    for pgid in groups:
        kill_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + STOP_GRACE_S
    while time.monotonic() < deadline and any(kill_group(g, 0) for g in groups):
        time.sleep(0.1)
    for pgid in groups:
        kill_group(pgid, signal.SIGKILL)
    shutil.rmtree(rd)


def down(ws, slug, out=sys.stdout):
    stop_all(ws, slug)
    if not state_path(ws, slug).exists():
        return
    state = load_state(ws, slug)
    for name, port in state["ports"].items():
        if is_held(port):
            out.write("warning: port %d for %s is still held\n" % (port, name))
    state["ports"] = {}
    save_state(ws, slug, state)


def close(ws, slug, out=sys.stdout):
    down(ws, slug, out)
    cfg = load_config(ws)
    if not state_path(ws, slug).exists():
        return
    state = load_state(ws, slug)
    worktree.remove(ws, cfg, slug, state)
    save_state(ws, slug, state)
