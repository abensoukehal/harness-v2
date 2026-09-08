"""An answered ask reopens what it parked (20.4)."""
from . import HarnessError
from .config import load_state, save_state


def answer(ws, slug, subtask_id, letter):
    state = load_state(ws, slug)
    by_id = {s["id"]: s for s in state["subtasks"]}
    st = by_id.get(subtask_id)
    if st is None:
        raise HarnessError("no sub-task %s in feature %s" % (subtask_id, slug))
    if st["status"] != "blocked" or st.get("reason") != "needs" or "ask" not in st:
        raise HarnessError("%s is not parked on a question (status %s, reason %s)" % (subtask_id, st["status"], st.get("reason", "none")))
    options = {o["letter"]: o["text"] for o in st["ask"]["options"]}
    if letter not in options:
        raise HarnessError("%s is not an option; choose one of %s" % (letter, ", ".join(sorted(options))))
    st["answer"] = {"letter": letter, "text": options[letter]}
    st["status"] = "pending"
    st.pop("reason", None)
    st.pop("last_error", None)
    reopened = []
    changed = True
    while changed:
        changed = False
        for other in state["subtasks"]:
            if other["status"] != "skipped" or not other.get("reason", "").startswith("depends on "):
                continue
            deps = [d.strip() for d in other["reason"][len("depends on "):].split(",")]
            if all(by_id[d]["status"] not in ("blocked", "skipped") for d in deps if d in by_id):
                other["status"] = "pending"
                other.pop("reason", None)
                reopened.append(other["id"])
                changed = True
    state["decisions"].append("%s · Ali chose %s: %s · ask" % (subtask_id, letter, options[letter]))
    if state["phase"] in ("finished", "delivery", "qa"):
        state["phase"] = "build"
    save_state(ws, slug, state)
    return reopened
