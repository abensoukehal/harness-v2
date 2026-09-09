"""Repeat before change (14.3): the engine moves on a first occurrence for four causes, and everything else waits for a second run."""
import re

from . import HarnessError

# Not a severity call. Four causes where the second occurrence is the one that costs: a run that reported green while
# it was not, a secret out of its file, a delivery that pushed the wrong thing or nothing, a guard that was stepped past.
FIRST_TIME = ("false-green", "secret", "delivery", "guard-bypassed")
HEADER = "cause | count | runs"


SLUG = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*$")


def check_cause(cause):
    if not SLUG.match(cause or ""):
        raise HarnessError("a cause is a lowercase slug, words joined by hyphens: %r" % cause)
    return cause


def names(cause, word):
    """Whole words only: 'secret' names the cause 'secret-in-log', 'secrets-dir' names nothing."""
    tokens, wanted = cause.split("-"), word.split("-")
    return any(tokens[i:i + len(wanted)] == wanted for i in range(len(tokens)))


def check_category(category):
    """The category is declared, never spelled out of a slug the retro invented (14.3)."""
    if category and category not in FIRST_TIME:
        raise HarnessError("a category is one of %s, or nothing: %r" % (", ".join(FIRST_TIME), category))
    return category


def eligible(cause, runs, category=None):
    """Whether the retro may change the engine for this cause now, and the sentence saying why."""
    # Declared wins over the slug. A wrongly immediate fix costs one early edit; a wrongly deferred one ships the defect,
    # so a slug that names one of the four still counts when nothing is declared.
    word = category or next((w for w in FIRST_TIME if names(cause, w)), None)
    if word:
        return True, "the cause is %r, which the engine changes for on the first occurrence" % word.replace("-", " ")
    if len(runs) > 1:
        return True, "seen in %d runs: %s" % (len(runs), ", ".join(runs))
    return False, ("seen in one run only, and the cause names none of: %s. It waits for a second run."
                   % ", ".join(w.replace("-", " ") for w in FIRST_TIME))


def parse(text):
    rows = []
    for line in text.splitlines()[1:]:
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 3 and parts[1].isdigit():
            rows.append({"cause": parts[0], "runs": [r.strip() for r in parts[2].split(",") if r.strip()]})
    return rows


def render(rows):
    return "\n".join([HEADER] + ["%s | %d | %s" % (r["cause"], len(r["runs"]), ", ".join(r["runs"])) for r in rows]) + "\n"


def record(ws, cause, run, category=None):
    """Append or increment the cause in product/frictions.md and answer whether the engine may change for it."""
    check_cause(cause)
    check_category(category)
    path = ws / "product" / "frictions.md"
    rows = parse(path.read_text()) if path.exists() else []
    row = next((r for r in rows if r["cause"] == cause), None)
    if row is None:
        row = {"cause": cause, "runs": []}
        rows.append(row)
    if run not in row["runs"]:  # one run counts once, however many times it hit the same cause
        row["runs"].append(run)
    path.write_text(render(rows))
    ok, why = eligible(cause, row["runs"], category)
    return {"cause": cause, "category": category, "count": len(row["runs"]), "runs": row["runs"], "eligible": ok, "why": why}
