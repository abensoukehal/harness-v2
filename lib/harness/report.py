"""The end-of-run report (13.2), from files only."""
import statistics

from .ask import render
from .config import feature_dir, load_config, load_state
from .cost import k, summary
from .gaps import parse_gaps

REASONS = {
    "criteria": "its checks stayed red after three attempts",
    "oracle": "a test written before the change looked wrong and was left alone",
    "budget": "it ran out of budget",
    "environment": "the running stacks kept failing under it",
    "needs": "it needs an answer, below",
    "missing_file": "it needed a file outside its list",
    "review": "the review found it not ready",
    "error": "the run lost track of it",
    "runtime": "the runtime declined to start its agent twice; a relaunch retries it",
    "unstable": "the run died on it three times",
    "pending": "the run stopped before it started",
    "running": "the run stopped while it was under way",
}


def status_of(state):
    """Zero done is nothing landed, whatever the reason; skipped counts against success exactly like blocked (10)."""
    if not any(s["status"] == "done" for s in state["subtasks"]):
        return "nothing landed"
    if state["phase"] != "finished" or not state.get("delivered"):
        return "partial"
    gaps = any(s["status"] != "done" for s in state["subtasks"]) or state["accepted_gaps"]
    return "done with gaps" if gaps else "done"


def relative(line, ws):
    """A path into this workspace is written from its root: an absolute one means nothing on a phone (13.2)."""
    return line.replace(str(ws) + "/", "").replace(str(ws), ".")


def cost_rows(text):
    """slug | tokens | distinct | wall | sub-tasks | blocked. A row written before distinct was counted carries five
    fields and reads as a zero there, so an older log still compares on the numbers it does have (6.2)."""
    rows = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split("|")]
        if not (len(parts) in (5, 6) and parts[1].isdigit()):
            continue
        if len(parts) == 5:
            parts = parts[:2] + ["0"] + parts[2:]
        rows.append({"slug": parts[0], "tokens": int(parts[1]), "distinct": int(parts[2]), "wall": int(parts[3]),
                     "subtasks": int(parts[4]), "blocked": int(parts[5])})
    return rows


def build_report(ws, slug):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    folder = feature_dir(ws, slug)
    status = status_of(state)
    done = [s for s in state["subtasks"] if s["status"] == "done"]
    missed = [s for s in state["subtasks"] if s["status"] != "done"]  # every sub-task lands in exactly one block (13.2)
    asks = [s for s in state["subtasks"] if s.get("ask")]
    lines = ["%s — %s" % (slug, status), "", "What works now."]
    lines += ["- " + s.get("goal", s["id"]) for s in done] or ["Nothing landed yet."]
    lines += ["", "What didn't land."]
    goal_of = {s["id"]: s.get("goal", s["id"]) for s in state["subtasks"]}
    for s in missed:
        why = s.get("reason", "") if s["status"] in ("blocked", "skipped") else s["status"]
        if why.startswith("depends on "):
            text = "waits on " + " and ".join(goal_of.get(d.strip(), d.strip()).lower() for d in why[len("depends on "):].split(","))
        else:
            text = REASONS.get(why, why)
        lines.append("- %s: %s" % (s.get("goal", s["id"]), text))
    if not missed:
        lines.append("Nothing." if done else "Nothing was planned.")
    for s in asks:
        # The report points at the feature folder once, at the end; the parked ask keeps its question and options only.
        body = [relative(l, ws) for l in render(s["ask"]).rstrip().splitlines() if not l.startswith(("Still running:", "Detail:"))]
        lines += [""] + body
    lines += ["", "Assumptions I made."]
    gaps = folder / "spec-gaps.md"
    entries = parse_gaps(gaps.read_text()) if gaps.exists() else []
    assumptions = ["- " + e["assumed"] for e in entries]  # one plain line each; the reasoning stays in spec-gaps.md (13.2)
    if state["kind"] != "service" and cfg.get("design", {}).get("comparable", True) is False:
        assumptions.append("- The design cannot be compared pixel for pixel, as the config declares, so no visual check ran.")
    lines += assumptions or ["None recorded."]
    agents = state.get("cost_by_agent", {})
    if agents:
        tokens = sum(a["tokens_in"] + a["tokens_out"] for a in agents.values())
        # Beside it, the context counted once instead of once per turn. The two rank the roles differently (6.2).
        distinct = sum(a.get("tokens_distinct", 0) + a["tokens_out"] for a in agents.values())
    else:
        tokens = sum(s.get("cost", {}).get("tokens_in", 0) + s.get("cost", {}).get("tokens_out", 0) for s in state["subtasks"])
        distinct = 0
    attempts = sum(s["attempts"] for s in state["subtasks"])
    wall = state.get("wall_time_s", 0)
    blocked = sum(1 for s in state["subtasks"] if s["status"] == "blocked")
    lines += ["", "What it cost.",
              "%s tokens (%s distinct), %d s wall time, %d sub-tasks, %d attempts, %d blocked."
              % (k(tokens), k(distinct), wall, len(state["subtasks"]), attempts, blocked)]
    if agents:
        lines.append("By role: " + "; ".join(summary(agents, wall)[:-1]) + ".")
    log = ws / "product" / "cost-log.md"
    earlier = [r for r in (cost_rows(log.read_text()) if log.exists() else []) if r["slug"] != slug][-3:]
    if len(earlier) == 3:
        lines.append("Last three runs: median %d tokens, %d s wall time." % (statistics.median(r["tokens"] for r in earlier), statistics.median(r["wall"] for r in earlier)))
    else:
        lines.append("No three earlier runs to compare against.")
    # The budget follows the plan: a fixed cost per run plus a rate per sub-task (6.2). A flat number taken from the
    # last run passes every plan larger than that one and so measures nothing.
    budget = cfg["budget"]["tokens_per_feature"] + cfg["budget"]["tokens_per_subtask"] * len(state["subtasks"])
    if tokens > budget:
        lines.append("Over the budget of %d tokens for %d sub-tasks: a harness defect to look at in the retro." % (budget, len(state["subtasks"])))
    lines += ["", "Next."]
    if asks:
        lines.append("Answer the question%s above first." % ("s" if len(asks) > 1 else ""))
    if status in ("partial", "nothing landed"):
        lines.append("The branch %s was not delivered; see the frictions in state." % state["branch"])
    elif cfg["delivery"]["mode"] == "branch":
        lines.append("Open a PR from %s." % state["branch"])
    else:
        lines.append("%s was merged into %s." % (state["branch"], cfg["delivery"]["target_branch"]))
    rel = "product/features/%s" % slug
    lines += ["", "Detail: %s/plan.md %s/decisions.md %s/state.json %s/gaps/" % (rel, rel, rel, rel)]
    text = "\n".join(lines) + "\n"
    (folder / "report.md").write_text(text)
    if log.exists() and slug not in {r["slug"] for r in cost_rows(log.read_text())}:
        with open(log, "a") as f:
            f.write("%s | %d | %d | %d | %d | %d\n" % (slug, tokens, distinct, wall, len(state["subtasks"]), blocked))
    return text
