"""spec-gaps.md (4.2): every entry carries the question, the answer the planner chose, and what it affects."""
import re

from . import HarnessError

FIELDS = ("Assumed", "Affects")


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
    return entries
