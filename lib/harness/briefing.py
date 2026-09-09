"""One worker's briefing for one sub-task (7.1). Criteria come from state.json, never plan.md. Nothing under secrets/ is read."""
import re

from . import HarnessError
from .config import load_config, load_state, stack_dir
from .plan import role_of

DEFAULT_CAP = 12000
RULES = [
    "No new file, abstraction layer or dependency without a one-line justification in the report.",
    "Never edit the safety net. Never start or stop a stack: return restart instead.",
    "Grep for the symbol, read about 50 lines around it. Whole file only under 150 lines.",
    "Return the structured result. Prose is refused.",
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


def criterion_text(c, expand):
    k = c["kind"]
    if k == "test":
        return "test " + c["pattern"]
    if k == "browser":
        return "browser " + c["script"]
    if k == "http":
        text = "http %s %s %d" % (c["method"], expand(c["url"]), c["expect_status"])
        return text + (", %s = %s" % (c["json_path"], c["value"]) if "json_path" in c else "")
    if k == "log":
        return 'log %s %s "%s"' % (c["stack"], "present" if c["present"] else "absent", c["pattern"])
    if k == "visual":
        return "visual %s %s" % (c["region"], c["reference"])
    if k == "examples":
        return "examples %s %s" % (c["set"], c["floor"])
    return k


def worktree_path(path, slug, cfg):
    """A plan path under repos/<repo>/ becomes the same path inside the feature worktree."""
    for stack in cfg["stacks"].values():
        repo = stack["repo"]
        if repo and (path == "repos/" + repo or path.startswith("repos/%s/" % repo)):
            return ".worktrees/%s/%s%s" % (slug, repo, path[len("repos/" + repo):])
    return path


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
    dependents = [s["id"] for s in state["subtasks"] if subtask_id in s.get("depends_on", [])]
    tokens = st.get("token_budget") or cfg["budget"]["tokens_per_subtask"]

    out = ["# Mission %s · %s" % (st["id"], st.get("goal", "")),
           "feature: %s   branch: %s" % (slug, state["branch"]),
           "workspace: %s" % ws,
           "stack: %s (%s)" % (name, role_of(name, stack)),
           "work in: " + str(stack_dir(ws, cfg, slug, name)),
           "files, open only these:"]
    out += ["  " + str(ws / worktree_path(f, slug, cfg)) for f in st.get("files", [])]
    if st.get("answer"):
        out.append("answer from Ali to your question: %s. %s" % (st["answer"]["letter"], st["answer"]["text"]))
    out += ["sub-tasks waiting for this one: " + (", ".join(dependents) or "none"),
            "line budget: %s      token budget: %d" % (st.get("line_budget", "unset"), tokens),
            "", "## Exit criteria"]
    out += ["- " + criterion_text(c, expand) for c in st["exit_criteria"]]

    out += ["", "## Stack"]
    for key in ["framework", "package_manager"]:
        if key in stack:
            out.append("%s: %s" % (key, stack[key]))
    commands = {k: v for k, v in stack["commands"].items() if k in ("test", "lint", "typecheck", "build")}
    if commands:
        out.append("commands:")
        out += ["  %s: %s" % (k, expand(v)) for k, v in commands.items()]
    runner = cfg["test_runner"].get(name)
    if runner:
        out.append("test runner: " + expand(runner))
    if "dev_url" in stack:
        out.append("dev url: " + expand(stack["dev_url"]))
    out.append("ports: " + " ".join("PORT_%s=%d" % (n.upper(), p) for n, p in sorted(ports.items())))
    out.append("log: %s" % (ws / ".run" / slug / (name + ".log")))
    folder = ws / "product" / "features" / slug
    out += ["", "## Paths, absolute; resolve none yourself",
            "safety net, never edited: %s" % (ws / "product" / "tests"),
            "decisions to append to: %s" % (folder / "decisions.md"),
            "conventions and code map: %s   %s" % (ws / "product" / "conventions.md", ws / "product" / "code-map")]

    out += ["", "## Conventions"]
    path = ws / "product" / "conventions.md"
    found = sections(path.read_text()) if path.exists() else {}
    for heading in ["all", name]:
        if found.get(heading):
            out += ["### " + heading, found[heading]]
    if out[-1] == "## Conventions":
        out.append("none recorded")

    examples = [c for c in st["exit_criteria"] if c["kind"] == "examples"]
    if examples:
        out += ["", "## Behaviour contract"]
        out += ["set: %s   floor: %s   temperature pinned, set seeded" % (c["set"], c["floor"]) for c in examples]
        out.append("Report failures as the failing examples, never as a score.")

    out += ["", "## Rules"] + ["- " + r for r in RULES]
    text = "\n".join(out) + "\n"
    cap = cfg["budget"].get("briefing_chars", DEFAULT_CAP)
    if len(text) > cap:
        conventions = len(path.read_text()) if path.exists() else 0
        raise HarnessError("briefing for %s is %d characters, cap %d; conventions.md is %d characters: consolidate it"
                           % (subtask_id, len(text), cap, conventions))
    return text
