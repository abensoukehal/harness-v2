"""The plan review (13.3): a summary, three numbers and a graph, rendered from the parsed plan. No model anywhere in here."""
from . import HarnessError
from .config import feature_dir, load_config, load_state, save_state
from .gaps import plain_problem
from .plan import parse

APPROVE = "A. Approve, and the build runs it."


def numbers(plan, cfg):
    """Sub-tasks, the most criteria on any one of them, how many reach into more than one stack."""
    paths = {name: s["path"] for name, s in cfg["stacks"].items() if s["path"]}
    spread = 0
    for st in plan["subtasks"]:
        touched = {n for n, p in paths.items() if any(f == p or f.startswith(p + "/") for f in st["files"])}
        spread += len(touched) > 1
    return len(plan["subtasks"]), max(len(s["exit_criteria"]) for s in plan["subtasks"]), spread


def graph(plan):
    """The sub-tasks and what waits on what, as Mermaid."""
    lines = ["graph TD"] + ['  %s["%s · %s"]' % (s["id"], s["id"], s["goal"].replace('"', "'")) for s in plan["subtasks"]]
    lines += ["  %s --> %s" % (dep, s["id"]) for s in plan["subtasks"] for dep in s["depends_on"]]
    return "\n".join(lines) + "\n"


def review(ws, slug):
    """Write the graph, render the message, and store it as the one the plan_ready push sends."""
    cfg = load_config(ws)
    folder = feature_dir(ws, slug)
    plan = parse((folder / "plan.md").read_text(), cfg, slug)
    (folder / "plan.mmd").write_text(graph(plan))
    count, criteria, spread = numbers(plan, cfg)
    body = ["%s — plan ready" % slug, ""]
    body += ["- " + s["goal"] for s in plan["subtasks"]]
    body += ["", "%d sub-tasks, at most %d criteria on one, %d reaching into more than one stack."
             % (count, criteria, spread), "", APPROVE, "Anything else you write is an edit to the plan, and this renders again."]
    for line in body:
        problem = plain_problem(line)
        if problem:
            raise HarnessError("the plan review is what Ali reads on a phone, and this line %s:\n  %s" % (problem, line))
    text = "\n".join(body + ["", "Detail: product/features/%s/plan.md product/features/%s/plan.mmd" % (slug, slug)]) + "\n"
    state = load_state(ws, slug)
    state["plan_message"] = text
    save_state(ws, slug, state)
    return text
