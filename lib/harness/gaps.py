"""spec-gaps.md (4.2): every entry carries the question, the answer the planner chose, and what it affects."""
import re

from . import HarnessError

FIELDS = ("Assumed", "Affects")
PLAIN_MAX = 160
# The report prints the assumption verbatim, so it obeys section 13: plain words, no path, no file name, no code.
CODE = re.compile(r"`|\$\{|[/\\]|\.(py|js|ts|tsx|jsx|md|json|ya?ml|sh|sql|html|css|java|kt|swift|rb|go|rs)\b|"
                  r"[a-zA-Z_]+\([^)]*\)|[<>{}]|\?[a-z_]+=|\bhttps?:")


def parse_gaps(text):
    """[{question, assumed, affects}] from the '## <question>' entries; an entry missing a field is refused, quoting the question."""
    entries, current = [], None
    for line in text.splitlines():
        if line.startswith("## "):
            current = {"question": line[3:].strip()}
            entries.append(current)
            continue
        m = re.match(r"^(Assumed|Affects):\s*(.+)$", line)
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
    return entries


def plain_problem(text):
    """Why this line cannot go in the report, or None."""
    if len(text) > PLAIN_MAX:
        return "runs to %d characters, past %d" % (len(text), PLAIN_MAX)
    m = CODE.search(text)
    if m:
        return "carries %r, which is code or a path" % m.group(0)
    return None
