"""Worker briefing from config, conventions and state (7.1). Reads nothing under secrets/."""
import re

from . import HarnessError
from .config import load_config, load_state, stack_dir

PROHIBITIONS = [
    "No new file without a one-line justification in the report.",
    "No new abstraction layer without a one-line justification in the report.",
    "No new dependency without a one-line justification in the report.",
]


def sections(text):
    """conventions.md as {heading: body}, headings being the '## ' lines."""
    out, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            out[current] = []
        elif current is not None:
            out[current].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def criterion_line(c):
    rest = " ".join("%s=%s" % (k, v) for k, v in c.items() if k != "kind")
    return ("- %s %s" % (c["kind"], rest)).rstrip()


def assemble(ws, slug, subtask_id):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    matches = [s for s in state["subtasks"] if s["id"] == subtask_id]
    if not matches:
        raise HarnessError("no sub-task %s in feature %s" % (subtask_id, slug))
    st = matches[0]
    name = st["stack"]
    stack = cfg["stacks"][name]
    ports = state["ports"]
    expand = lambda text: re.sub(r"\$\{PORT_(\w+)\}", lambda m: str(ports.get(m.group(1).lower(), m.group(0))), text)

    profile = ["# Technical profile", "stack: " + name]
    for key in ["framework", "package_manager", "logs"]:
        if key in stack:
            profile.append("%s: %s" % (key, stack[key]))
    profile.append("directory: " + str(stack_dir(ws, cfg, slug, name).relative_to(ws)))
    if "dev_url" in stack:
        profile.append("dev_url: " + expand(stack["dev_url"]))
    profile.append("health: " + ("log" if "log" in stack["health"] else "http"))
    profile.append("commands:")
    profile += ["  %s: %s" % (k, expand(v)) for k, v in stack["commands"].items()]
    profile.append("ports: " + ", ".join("PORT_%s=%d" % (n.upper(), p) for n, p in sorted(ports.items())))

    conventions = ["# Conventions"]
    path = ws / "product" / "conventions.md"
    found = sections(path.read_text()) if path.exists() else {}
    for heading in ["all", name]:
        if found.get(heading):
            conventions += ["## " + heading, found[heading]]
    if len(conventions) == 1:
        conventions.append("none recorded")

    dependents = [s["id"] for s in state["subtasks"] if subtask_id in s.get("depends_on", [])]
    budget = st.get("token_budget") or max(1, cfg["budget"]["tokens_per_feature"] // max(1, len(state["subtasks"])))
    mission = ["# Mission", "id: " + st["id"], "goal: " + st.get("goal", ""),
               "files:"] + ["  " + f for f in st.get("files", [])] + [
               "criteria:"] + [criterion_line(c) for c in st.get("exit_criteria", [])] + [
               "line_budget: %s" % st.get("line_budget", "unset"),
               "token_budget: %d" % budget,
               "depends_on_this: " + (", ".join(dependents) or "none"),
               "prohibitions:"] + ["  " + p for p in PROHIBITIONS]
    return "\n".join(profile + [""] + conventions + [""] + mission) + "\n"
