import json
import os
import subprocess

import yaml

from . import HARNESS_ROOT, HarnessError, git

VALIDATE = HARNESS_ROOT / "bin" / "validate"


def validate(path, schema=None):
    args = [str(VALIDATE), str(path)] + (["--schema", schema] if schema else [])
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise HarnessError(done.stderr.strip())


def config_path(ws):
    return ws / "product" / "client.config.yaml"


def load_config(ws):
    path = config_path(ws)
    validate(path, "config")
    with open(path) as f:
        return yaml.safe_load(f)


def read_config(ws):
    """The config without the checks that read secrets/. Setup uses this: a workspace has to exist before anyone can
    put a credential in it, so init and link read the shape and every command that runs a stack calls load_config."""
    with open(config_path(ws)) as f:
        return yaml.safe_load(f)


def feature_dir(ws, slug):
    return ws / "product" / "features" / slug


def state_path(ws, slug):
    return feature_dir(ws, slug) / "state.json"


def load_state(ws, slug):
    path = state_path(ws, slug)
    if not path.exists():
        raise HarnessError("no state for feature %s: run /harness-plan %s first" % (slug, slug))
    validate(path, "state")
    with open(path) as f:
        return json.load(f)


def save_state(ws, slug, state):
    path = state_path(ws, slug)
    tmp = path.with_name("state.json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    try:
        validate(tmp, "state")
    except HarnessError:
        tmp.unlink()
        raise
    os.replace(tmp, path)


def create_state(ws, slug, kind):
    cfg = load_config(ws)
    state = {
        "feature": slug,
        "kind": kind,
        "harness_commit": git("rev-parse", "HEAD", cwd=ws / "harness"),
        "branch": cfg["delivery"]["branch_prefix"] + slug,
        "phase": "ingestion",
        "ports": {},
        "worktrees": {},
        "subtasks": [],
        "decisions": [],
        "frictions": [],
        "accepted_gaps": [],
    }
    feature_dir(ws, slug).mkdir(parents=True, exist_ok=True)
    save_state(ws, slug, state)
    return state


def branch_of(cfg, key, repo):
    """base_branch and target_branch are one branch for every repo, or one per repo keyed by repo name (10).
    A map is checked against the repos the stacks name at validation, so every repo reaching here has an entry."""
    value = cfg["delivery"][key]
    return value if isinstance(value, str) else value[repo]


def stack_dir(ws, cfg, slug, name):
    """Where a stack lives inside the feature's worktree (11.2): repos/<repo>/x maps to .worktrees/<slug>/<repo>/x."""
    stack = cfg["stacks"][name]
    if stack["repo"] is None:
        return ws
    inside = stack["path"][len("repos/" + stack["repo"]):].lstrip("/")
    return ws / ".worktrees" / slug / stack["repo"] / inside
