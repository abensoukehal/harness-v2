"""The end-of-run report (13.2), from files only."""
import statistics

from .ask import render
from .config import feature_dir, load_config, load_state
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
    "unstable": "the run died on it three times",
    "pending": "the run stopped before it started",
    "running": "the run stopped while it was under way",
}


def status_of(state):
    if state["phase"] != "finished" or state.get("delivered") is False:
        return "partial"
    gaps = any(s["status"] in ("blocked", "skipped") for s in state["subtasks"]) or state["accepted_gaps"]
    return "done with gaps" if gaps else "done"


def cost_rows(text):
    rows = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 5 and parts[1].isdigit():
            rows.append({"slug": parts[0], "tokens": int(parts[1]), "wall": int(parts[2]), "subtasks": int(parts[3]), "blocked": int(parts[4])})
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
        body = [l for l in render(s["ask"]).rstrip().splitlines() if not l.startswith(("Still running:", "Detail:"))]
        lines += [""] + body
    lines += ["", "Assumptions I made."]
    gaps = folder / "spec-gaps.md"
    entries = parse_gaps(gaps.read_text()) if gaps.exists() else []
    lines += ["- %s %s" % (e["question"], e["assumed"]) for e in entries] or ["None recorded."]
    tokens = sum(s.get("cost", {}).get("tokens_in", 0) + s.get("cost", {}).get("tokens_out", 0) for s in state["subtasks"])
    attempts = sum(s["attempts"] for s in state["subtasks"])
    wall = state.get("wall_time_s", 0)
    blocked = sum(1 for s in state["subtasks"] if s["status"] == "blocked")
    lines += ["", "What it cost.",
              "%d tokens, %d s wall time, %d sub-tasks, %d attempts, %d blocked." % (tokens, wall, len(state["subtasks"]), attempts, blocked)]
    log = ws / "product" / "cost-log.md"
    earlier = [r for r in (cost_rows(log.read_text()) if log.exists() else []) if r["slug"] != slug][-3:]
    if len(earlier) == 3:
        lines.append("Last three runs: median %d tokens, %d s wall time." % (statistics.median(r["tokens"] for r in earlier), statistics.median(r["wall"] for r in earlier)))
    else:
        lines.append("No three earlier runs to compare against.")
    if tokens > cfg["budget"]["tokens_per_feature"]:
        lines.append("Over the feature budget of %d tokens: a harness defect to look at in the retro." % cfg["budget"]["tokens_per_feature"])
    lines += ["", "Next."]
    if asks:
        lines.append("Answer the question%s above first." % ("s" if len(asks) > 1 else ""))
    if status == "partial":
        lines.append("The branch %s was not delivered; see the frictions in state." % state["branch"])
    elif cfg["delivery"]["mode"] == "pr":
        lines.append("Open a PR from %s." % state["branch"])
    else:
        lines.append("%s was merged into %s." % (state["branch"], cfg["delivery"]["target_branch"]))
    rel = "product/features/%s" % slug
    lines += ["", "Detail: %s/plan.md %s/decisions.md %s/state.json %s/gaps/" % (rel, rel, rel, rel)]
    text = "\n".join(lines) + "\n"
    (folder / "report.md").write_text(text)
    if log.exists() and slug not in {r["slug"] for r in cost_rows(log.read_text())}:
        with open(log, "a") as f:
            f.write("%s | %d | %d | %d | %d\n" % (slug, tokens, wall, len(state["subtasks"]), blocked))
    return text
