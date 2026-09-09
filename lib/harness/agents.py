"""Model and effort per role (6.3): config, static per workspace, passed to every spawn."""
import json
import sys

from .config import load_config

ROLES = ("planner", "test-writer", "worker", "reviewer", "qa", "retro", "io")
# The io steps run a command and copy its output, so they run at low effort. Every other role inherits the session.
DEFAULTS = {role: {} for role in ROLES}
DEFAULTS["io"] = {"effort": "low"}


def options(cfg):
    """{role: {model?, effort?}} in the shape agent() takes. 'inherit' and an absent key both mean the session's own setting."""
    declared = cfg.get("agents") or {}
    out = {}
    for role in ROLES:
        opts = dict(DEFAULTS[role])
        for key, value in (declared.get(role) or {}).items():
            if value == "inherit":
                opts.pop(key, None)
            else:
                opts[key] = value
        out[role] = opts
    return out


def show(ws, out=sys.stdout):
    out.write(json.dumps(options(load_config(ws)), indent=2) + "\n")
