"""The next round of the build loop (phase 4): which sub-tasks run, which are skipped, nothing halts."""
from . import HarnessError
from .config import load_config, load_state, save_state

MAX_PARALLEL = 4
DEAD = ("blocked", "skipped")


def reopen(state):
    """Skipped sub-tasks whose dependencies are no longer blocked or skipped go back to pending, transitively. Returns their ids."""
    by_id = {s["id"]: s for s in state["subtasks"]}
    reopened, changed = [], True
    while changed:
        changed = False
        for st in state["subtasks"]:
            if st["status"] != "skipped" or not st.get("reason", "").startswith("depends on "):
                continue
            deps = [d.strip() for d in st["reason"][len("depends on "):].split(",")]
            if all(by_id[d]["status"] not in DEAD for d in deps if d in by_id):
                st["status"] = "pending"
                st.pop("reason", None)
                reopened.append(st["id"])
                changed = True
    return reopened


def next_batch(ws, slug):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    by_id = {s["id"]: s for s in state["subtasks"]}
    skipped = []
    for st in state["subtasks"]:
        if st["status"] == "running":
            st.update(status="blocked", reason="error", last_error="left running by a failed round")
    for st in state["subtasks"]:
        dead = [d for d in st.get("depends_on", []) if by_id[d]["status"] in DEAD]
        if st["status"] == "pending" and dead:
            st.update(status="skipped", reason="depends on " + ", ".join(dead))
            skipped.append(st["id"])
    pending = [s for s in state["subtasks"] if s["status"] == "pending"]
    ready, repos = [], set()
    for st in pending:
        if any(by_id[d]["status"] != "done" for d in st.get("depends_on", [])):
            continue
        repo = cfg["stacks"][st["stack"]]["repo"]
        if repo in repos or len(ready) == MAX_PARALLEL:
            continue
        repos.add(repo)
        ready.append(st["id"])
    save_state(ws, slug, state)
    if pending and not ready:
        raise HarnessError("no runnable sub-task among %s: their dependencies are neither done nor dead" % ", ".join(s["id"] for s in pending))
    return {"ready": ready, "skipped": skipped, "pending": len(pending)}
