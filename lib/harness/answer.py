"""An answered ask reopens what it parked (20.4)."""
from . import HarnessError
from .config import load_state, save_state
from .next import reopen


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
    reopened = reopen(state)
    state["decisions"].append("%s · Ali chose %s: %s · ask" % (subtask_id, letter, options[letter]))
    # Autonomy is the pillar the rest are subordinate to, so the run counts what it could not decide alone (6.2).
    state["interventions"].append({"phase": state["phase"], "cause": "answered-ask",
                                   "line": "%s waited on a question and Ali answered %s" % (subtask_id, letter)})
    if state["phase"] in ("finished", "delivery", "qa"):
        state["phase"] = "build"
    save_state(ws, slug, state)
    return reopened
