"""Strict parser for plan.md (4.1). Every refusal quotes the offending line."""
import re

from . import HarnessError
from .agents import options as agent_options

KINDS = ("ui", "service", "mixed")
HEADING = re.compile(r"^## (st-[0-9]{2,}) · (.+)$")
FIELD = re.compile(r"^([a-z_]+):\s*(.*)$")
REQUIRED = ["stack", "files", "depends_on", "line_budget", "criteria"]
MAX_CRITERIA = 5
METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
MAX_SUBTASKS = 20
ROLE_HINTS = [("frontend", ("web", "ui", "frontend", "front")), ("mobile", ("mobile", "ios", "android", "app")),
              ("ai", ("ai", "llm", "model"))]


class PlanError(HarnessError):
    pass


def role_of(name, stack):
    if stack.get("role"):
        return stack["role"]
    lowered = name.lower()
    for role, hints in ROLE_HINTS:
        if any(h in lowered for h in hints):
            return role
    return "backend"


def parse(text, cfg, slug=None):
    lines = text.splitlines()
    stacks = cfg["stacks"]

    def fail(i, problem):
        raise PlanError("plan.md line %d: %s\n  %s" % (i + 1, problem, lines[i]))

    kind, subtasks, current, in_criteria = None, [], None, False
    for i, raw in enumerate(lines):
        line = raw.rstrip()
        if not line.strip():
            continue
        m = HEADING.match(line)
        if m:
            if len(subtasks) == MAX_SUBTASKS:
                fail(i, "more than %d sub-tasks: this is more than one feature" % MAX_SUBTASKS)
            if any(s["id"] == m.group(1) for s in subtasks):
                fail(i, "duplicate sub-task id")
            current = {"id": m.group(1), "goal": m.group(2).strip(), "_line": i, "_criteria": []}
            subtasks.append(current)
            in_criteria = False
            continue
        if current is None:
            if line.startswith("# "):
                continue
            fm = FIELD.match(line)
            if fm and fm.group(1) == "kind":
                if fm.group(2).strip() not in KINDS:
                    fail(i, "kind must be one of %s" % ", ".join(KINDS))
                kind = fm.group(2).strip()
                continue
            fail(i, "only the title and 'kind:' may appear before the first sub-task")
        if line.startswith("## "):
            fail(i, "sub-task heading must read '## st-NN · <goal>'")
        if line.startswith("- "):
            if not in_criteria:
                fail(i, "list item outside 'criteria:'")
            current["_criteria"].append((i, line[2:].strip()))
            continue
        fm = FIELD.match(line)
        if not fm:
            fail(i, "expected 'field: value'")
        key, value = fm.group(1), fm.group(2).strip()
        if key == "criteria":
            if value:
                fail(i, "criteria are one '- ' line each below 'criteria:'")
            in_criteria = True
            current["criteria"] = True
            continue
        if key not in REQUIRED:
            fail(i, "unknown field %r" % key)
        in_criteria = False
        current[key] = (i, value)

    if not subtasks:
        raise PlanError("plan.md: no sub-task")
    if kind is None:
        fail(subtasks[0]["_line"], "missing 'kind: ui | service | mixed' before the first sub-task")

    comparable = cfg.get("design", {}).get("comparable", True)
    ids = [s["id"] for s in subtasks]
    out, texts = [], {}
    for st in subtasks:
        for key in REQUIRED:
            if key not in st:
                fail(st["_line"], "missing field %r" % key)
        i, stack = st["stack"]
        if "," in stack or len(stack.split()) > 1:
            fail(i, "a sub-task runs in one stack; name one of %s and split the rest into their own sub-tasks" % ", ".join(sorted(stacks)))
        if stack not in stacks:
            fail(i, "unknown stack %r; config has %s" % (stack, ", ".join(sorted(stacks))))
        if stacks[stack]["repo"] is None:
            fail(i, "stack %r has no repo: the run starts it but never edits it" % stack)
        i, files = st["files"]
        files = [f.strip() for f in files.split(",") if f.strip()]
        if not files:
            fail(i, "files must list at least one path")
        home = "repos/%s/" % stacks[stack]["repo"]
        for f in files:
            if not f.startswith(home):
                fail(i, "file %r is outside %s, the repo of stack %r: a sub-task runs in one stack" % (f, home.rstrip("/"), stack))
        i, deps = st["depends_on"]
        deps = [] if deps == "none" else [d.strip() for d in deps.split(",") if d.strip()]
        for d in deps:
            if d == st["id"]:
                fail(i, "a sub-task cannot depend on itself")
            if d not in ids:
                fail(i, "depends on %r which is not a sub-task in this plan" % d)
        i, budget = st["line_budget"]
        if not budget.isdigit():
            fail(i, "line_budget must be a whole number")
        if not st["_criteria"]:
            fail(st["_line"], "sub-task has no criterion")
        if len(st["_criteria"]) > MAX_CRITERIA:
            fail(st["_criteria"][MAX_CRITERIA][0], "sub-task carries %d criteria, past %d: it is more than one sub-task"
                 % (len(st["_criteria"]), MAX_CRITERIA))
        criteria = [criterion(i, text, cfg, stack, fail, comparable) for i, text in st["_criteria"]]
        texts[st["id"]] = [text for _, text in st["_criteria"]]  # what a gap's 'Pinned:' resolves against (4.2)
        out.append({"id": st["id"], "stack": stack, "goal": st["goal"], "files": files, "depends_on": deps,
                    "line_budget": int(budget), "exit_criteria": criteria, "status": "pending", "attempts": 0,
                    "interruptions": 0, "worktree": ".worktrees/%s/%s" % (slug, stacks[stack]["repo"]),
                    "role": role_of(stack, stacks[stack])})
    cycle = find_cycle({s["id"]: s["depends_on"] for s in out})
    if cycle:
        fail(next(s["_line"] for s in subtasks if s["id"] == cycle[0]), "dependency cycle: %s" % " > ".join(cycle))
    # A kind that activates the visual diff and a plan without one must disagree loudly (4.0, 5.3); only a declared
    # design.comparable: false in the config lets a screen feature skip it.
    if kind in ("ui", "mixed") and comparable and not any(c["kind"] == "visual" for s in out for c in s["exit_criteria"]):
        fail(subtasks[0]["_line"], "kind %s activates the visual diff and no sub-task carries a visual criterion; add one or declare design.comparable: false in the config" % kind)
    return {"kind": kind, "subtasks": out, "comparable": comparable, "criteria_text": texts}


def find_cycle(deps):
    """One cycle in the dependency graph as the ids around it, or None. The plan declares order; nothing infers it from the file."""
    state, trail = {}, []

    def visit(node):
        if state.get(node) == "open":
            return trail[trail.index(node):] + [node]
        if state.get(node) == "closed":
            return None
        state[node] = "open"
        trail.append(node)
        for dep in deps.get(node, []):
            found = visit(dep)
            if found:
                return found
        trail.pop()
        state[node] = "closed"
        return None

    for node in deps:
        found = visit(node)
        if found:
            return found
    return None


def criterion(i, text, cfg, stack, fail, comparable=True):
    """One criterion line. Its verb must resolve to a command the config defines for this stack (4.1), or the plan is refused here."""
    stacks = cfg["stacks"]
    parts = text.split()
    kind, rest = parts[0], parts[1:]

    def needs(key, where, value):
        if not value:
            fail(i, "criterion %r needs %s.%s in the config, which is missing" % (kind, where, key))

    if kind == "test" and len(rest) == 1:
        needs(stack, "test_runner", cfg["test_runner"].get(stack))
        return {"kind": "test", "pattern": rest[0]}
    if kind == "browser" and len(rest) == 1:
        needs(stack, "browser_runner", cfg.get("browser_runner", {}).get(stack))
        return {"kind": "browser", "script": rest[0]}
    if kind in ("lint", "typecheck") and not rest:
        needs(kind, "stacks.%s.commands" % stack, stacks[stack]["commands"].get(kind))
        return {"kind": kind}
    if kind == "visual" and len(rest) == 2:
        needs("threshold_pct", "visual", cfg.get("visual"))
        if not comparable:
            fail(i, "the config declares design.comparable: false, so nothing can be compared against")
        return {"kind": "visual", "region": rest[0], "reference": rest[1]}
    if kind == "http" and len(rest) >= 3:
        method, url, status = rest[0].upper(), rest[1], rest[2]
        if method not in METHODS:
            fail(i, "http method must be one of %s" % ", ".join(sorted(METHODS)))
        if not status.isdigit() or not 100 <= int(status) <= 599:
            fail(i, "http status must be a number from 100 to 599")
        c = {"kind": "http", "method": method, "url": url, "expect_status": int(status)}
        tail = " ".join(rest[3:])
        if tail:
            if " = " not in tail:
                fail(i, "http assertion reads '<json path> = <value>'")
            path, value = tail.split(" = ", 1)
            c["json_path"], c["value"] = path.strip(), value.strip()
        return c
    if kind == "log" and len(rest) >= 3:
        stack, presence = rest[0], rest[1]
        if stack not in stacks:
            fail(i, "log criterion names unknown stack %r" % stack)
        if presence not in ("present", "absent"):
            fail(i, "log criterion reads 'log <stack> <present|absent> <regex>'")
        return {"kind": "log", "stack": stack, "present": presence == "present", "pattern": " ".join(rest[2:])}
    if kind == "examples" and len(rest) == 2:
        try:
            floor = float(rest[1])
        except ValueError:
            fail(i, "examples floor must be a number")
        if not 0 <= floor < 1:
            fail(i, "examples floor must be at least 0 and below 1; never 100%")
        return {"kind": "examples", "set": rest[0], "floor": floor}
    fail(i, "not a criterion: kinds are test, http, browser, log, visual, lint, typecheck, examples")


def config_block(cfg):
    return {
        "stacks": {name: {"repo": s["repo"], "role": role_of(name, s)} for name, s in cfg["stacks"].items()},
        "max_fixes": cfg["qa"]["max_fixes"],
        "mode": cfg["delivery"]["mode"],
        "branch_prefix": cfg["delivery"]["branch_prefix"],
        "target_branch": cfg["delivery"]["target_branch"],
        "agents": agent_options(cfg),
        "events": cfg["notify"]["events"],
    }
