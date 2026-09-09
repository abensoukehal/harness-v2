"""spec-gaps.md (4.2): every entry carries the question, the answer the planner chose, what it affects, and the criterion that pins it."""
import re

from . import HarnessError

FIELDS = ("Assumed", "Affects", "Pinned")
PLAIN_MAX = 160
# The report prints the assumption verbatim, so it obeys section 13: plain words, no path, no file name, no code.
CODE = re.compile(r"`|\$\{|[/\\]|\.(py|js|ts|tsx|jsx|md|json|ya?ml|sh|sql|html|css|java|kt|swift|rb|go|rs)\b|"
                  r"[a-zA-Z_]+\([^)]*\)|[<>{}]|\?[a-z_]+=|\bhttps?:")


def parse_gaps(text, criteria=None):
    """[{question, assumed, affects, pinned}] from the '## <question>' entries; an entry missing a field is refused, quoting the question.

    With criteria ({sub-task id: [criterion line]} from plan.md), an entry whose 'Pinned:' names no criterion that exists
    is refused too: an answer nothing tests is a decision the run never checks."""
    entries, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            current = {"question": line[3:].strip()}
            entries.append(current)
            continue
        m = re.match(r"^(Assumed|Affects|Pinned):\s*(.+)$", line)
        if m and current is not None:
            current[m.group(1).lower()] = m.group(2).strip()
    for e in entries:
        for field in FIELDS:
            if not e.get(field.lower()):
                raise HarnessError("spec-gaps.md entry has no '%s:' line, so it is a question nobody answered:\n  ## %s" % (field, e["question"]))
        problem = plain_problem(e["assumed"])
        if problem:
            raise HarnessError("spec-gaps.md 'Assumed:' is one plain line the report prints as it stands, and this one %s.\n"
                               "Put the reasoning in the lines below it, which stay in this file:\n  ## %s\n  Assumed: %s"
                               % (problem, e["question"], e["assumed"]))
        if criteria is not None:
            pinned(e, criteria)
    return entries


def pinned(entry, criteria):
    """'Pinned: <st-NN> <criterion line>' must name a criterion plan.md carries, or the answer is unverified."""
    parts = entry["pinned"].split(None, 1)
    known = criteria.get(parts[0], []) if len(parts) == 2 else []
    if len(parts) != 2 or parts[1].strip() not in known:
        raise HarnessError("spec-gaps.md 'Pinned:' names no criterion in plan.md, so nothing tests this answer.\n"
                           "Pin it to a criterion the plan carries, or ask the question instead of assuming it:\n"
                           "  ## %s\n  Pinned: %s" % (entry["question"], entry["pinned"]))


def plain_problem(text):
    """Why this line cannot go in the report, or None."""
    if len(text) > PLAIN_MAX:
        return "runs to %d characters, past %d" % (len(text), PLAIN_MAX)
    m = CODE.search(text)
    if m:
        return "carries %r, which is code or a path" % m.group(0)
    return None
