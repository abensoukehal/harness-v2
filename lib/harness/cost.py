"""Cost from the runtime's own transcripts (6.2): input tokens per agent, not output deltas. One record per agent, keyed by agent id.

Two numbers, not one. tokens_in sums every turn's input, so an agent's context is counted once per turn it takes;
tokens_distinct counts it once. The two rank the roles differently — a fifty-turn agent looks expensive under the
first and cheap under the second — and only the second says where the context is actually going.
"""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from . import HarnessError
from .config import load_state, save_state

ROLES = {"workflow-subagent": "io"}
TOOL_KINDS = {"Grep": "locate", "Glob": "locate", "Read": "read", "NotebookRead": "read",
              "Write": "write", "Edit": "write", "NotebookEdit": "write"}
# Shell heads that answer the same two questions. A head this map does not know makes the turn other, which is
# where a shell write lands: `sed -i`, a redirect and a heredoc all read as other, and other is the denominator.
SHELL_KINDS = {"grep": "locate", "egrep": "locate", "fgrep": "locate", "rg": "locate", "find": "locate", "ls": "locate",
               "cat": "read", "head": "read", "tail": "read", "sed": "read"}
ORDER = ["write", "read", "locate", "other"]
HEAD = re.compile(r"(?:\A|[|;&\n(])\s*(?:sudo\s+|time\s+)?([A-Za-z][\w.-]*)")
REDIRECT = re.compile(r"<<|(?<![0-9])>")  # a heredoc or a redirect wrote a file, whatever the command in front of it was


def transcript_dirs(explicit):
    """One directory per workflow run. A session folder holds every run it ever launched, so cost is grouped by run, never by folder (6.2)."""
    if explicit:
        return [Path(d) for d in explicit]
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        raise HarnessError("no transcripts: pass --transcripts DIR or run inside a session")
    dirs = sorted(Path.home().glob(".claude/projects/*/%s/subagents/workflows/*" % sid))
    if not dirs:
        raise HarnessError("no workflow transcripts for session %s" % sid)
    return dirs


def shell_kind(command):
    """One shell turn: locate only when every command in it locates. One `cat` in the pipeline and the turn read."""
    if REDIRECT.search(command):
        return "write"
    kinds = {SHELL_KINDS.get(h, "other") for h in HEAD.findall(command)} or {"other"}
    if kinds == {"locate"}:
        return "locate"
    return "read" if kinds <= {"locate", "read"} else "other"


def turn_kind(content):
    """What one turn did: locate (a grep, glob or find, whose result is paths and line numbers), read (file content
    into context), write, or other. A turn that locates and reads is a read turn, so the locate share counts the
    turns an agent spends finding its ground before it reads anything (6.2). Only the locate count is recorded: the
    other three decide it and nothing reads them back (6.2.1)."""
    kinds = set()
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "tool_use":
            name = b.get("name", "")
            kinds.add(shell_kind(str(b.get("input", {}).get("command", ""))) if name == "Bash"
                      else TOOL_KINDS.get(name, "other"))
    for kind in ORDER:
        if kind in kinds:
            return kind
    return "other"


def text_of(content):
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict))


def seconds(stamp):
    return datetime.strptime(stamp[:19], "%Y-%m-%dT%H:%M:%S").timestamp()


def record(path, slug, ws):
    """One agent's transcript: None unless its first message names the feature and the workspace, since one session can serve several workspaces."""
    meta = path.with_suffix(".meta.json")
    role = json.loads(meta.read_text()).get("agentType", "io") if meta.exists() else "io"
    role = ROLES.get(role, role)
    first, tokens_in, tokens_out, turns, start, end = None, 0, 0, 0, None, None
    distinct = 0
    locate = 0
    model, effort = None, None
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("type") == "user" and first is None:
            first = text_of(e["message"]["content"])
        elif e.get("type") == "assistant":
            u = e["message"].get("usage", {})
            tokens_in += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0)
            tokens_out += u.get("output_tokens", 0)
            # Distinct: what this agent was handed once. The first turn's cache read is its prefix; every later turn
            # re-reads what the turns before it already established, and that read is not new context.
            distinct += u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            if not turns:
                distinct += u.get("cache_read_input_tokens", 0)
            turns += 1
            locate += turn_kind(e["message"].get("content", [])) == "locate"
            # The pair that spent these tokens, read from the transcript: what ran, not what the config asked for (6.3).
            model = e["message"].get("model") or model
            effort = e.get("effort") or effort
        stamp = e.get("timestamp")
        if stamp:
            start = start or stamp
            end = stamp
    if first is None or not re.search(r"%s(?![\w-])" % re.escape(str(ws)), first) or not re.search(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(slug), first):
        return None
    # run: which workflow launch this agent belonged to, so a second run of the same feature keeps its own span (6.2).
    out = {"role": role, "run": path.parent.name, "model": model or "unknown", "effort": effort or "inherit",
           "tokens_in": tokens_in, "tokens_distinct": distinct, "tokens_out": tokens_out,
           "turns": turns, "locate_turns": locate,
           "duration_s": int(seconds(end) - seconds(start)) if start and end else 0}
    m = re.search(r"\bst-[0-9]{2,}\b", first[:400])
    if m:
        out["subtask"] = m.group(0)
    return out, (seconds(start) if start else None, seconds(end) if end else None)


def discarded(ordered):
    """The tokens spent on a diff that did not survive (6.2).

    An attempt starts at a worker spawn and runs until the next one, so a retry, a convention return and a respawn
    each open one. Every attempt but the last was superseded, and what it spent was paid for nothing. `attempts`
    cannot answer this: a respawn the runtime forced redid landed work and left the count at 1 by rule.

    The spawns before the first worker are the sub-task's own setup, not an attempt, and they are not counted.
    """
    attempts, current = [], None
    for a in ordered:
        if a["role"] == "worker":
            if current is not None:
                attempts.append(current)
            current = []
        if current is not None:
            current.append(a)
    if current is not None:
        attempts.append(current)
    return sum(a["tokens_in"] for spent in attempts[:-1] for a in spent)


def cost(ws, slug, dirs=None, out=sys.stdout):
    state = load_state(ws, slug)
    agents = state.setdefault("cost_by_agent", {})
    spans = {}
    started = {}
    for d in transcript_dirs(dirs):
        for path in sorted(d.glob("agent-*.jsonl")):
            found = record(path, slug, ws)
            if found:
                agents[path.stem[len("agent-"):]], span = found
                spans.setdefault(d.name, []).append(span)
                started[path.stem[len("agent-"):]] = span[0] or 0
    by_id = {s["id"]: s for s in state["subtasks"]}
    for st in by_id.values():
        mine = [a for i, a in agents.items() if a.get("subtask") == st["id"]]
        if not mine:
            continue
        c = st.setdefault("cost", {"tokens_in": 0, "tokens_out": 0, "duration_s": 0})
        c["tokens_in"] = sum(a["tokens_in"] for a in mine)
        c["tokens_out"] = sum(a["tokens_out"] for a in mine)
        c["duration_s"] = c["duration_s"] or sum(a["duration_s"] for a in mine)
        # In the order they ran, from the transcripts' own spans: state carries durations, never a clock.
        ordered = [a for _, a in sorted(((started.get(i, 0), a) for i, a in agents.items()
                                         if a.get("subtask") == st["id"]), key=lambda pair: pair[0])]
        c["tokens_discarded"] = discarded(ordered)
    # Wall time is the sum of each run's own span. Measuring from the first agent to the last across runs would
    # bill the hours between a plan and the build launched the next morning.
    wall = 0
    for run, pairs in spans.items():
        starts = [s for s, _ in pairs if s]
        ends = [e for _, e in pairs if e]
        if starts and ends:
            wall += int(max(ends) - min(starts))
    state["wall_time_s"] = max(state.get("wall_time_s", 0), wall)
    save_state(ws, slug, state)
    for line in summary(agents, state["wall_time_s"]):
        out.write(line + "\n")
    return agents


def share(locate, turns):
    """The locate share: the turns spent finding ground, over every turn taken. It is comparable across features of
    different sizes and across repos, because it does not depend on what the agent went on to write (6.2)."""
    return round(100 * locate / turns) if turns else 0


def summary(agents, wall):
    """Per role: the per-turn total, the distinct context beside it, the output, the turns and the locate share (6.2)."""
    roles = {}
    for a in agents.values():
        r = roles.setdefault(a["role"], [0, 0, 0, 0, set(), 0, 0])
        r[0] += a["tokens_in"]
        r[1] += a.get("tokens_distinct", 0)
        r[2] += a["tokens_out"]
        r[3] += 1
        if a.get("model"):
            r[4].add("%s/%s" % (a["model"], a.get("effort", "inherit")))
        r[5] += a.get("turns", 0)
        r[6] += a.get("locate_turns", 0)
    lines = ["%s: %d agents, %s in (%s distinct), %s out, %d turns, %d%% locate%s"
             % (role, n, k(i), k(d), k(o), t, share(loc, t), " (%s)" % ", ".join(sorted(pairs)) if pairs else "")
             for role, (i, d, o, n, pairs, t, loc) in sorted(roles.items(), key=lambda kv: -kv[1][0])]
    total_in = sum(a["tokens_in"] for a in agents.values())
    total_distinct = sum(a.get("tokens_distinct", 0) for a in agents.values())
    total_out = sum(a["tokens_out"] for a in agents.values())
    total_turns = sum(a.get("turns", 0) for a in agents.values())
    total_locate = sum(a.get("locate_turns", 0) for a in agents.values())
    runs = len({a.get("run") for a in agents.values() if a.get("run")})
    lines.append("total: %d agents over %d run%s, %s in (%s distinct), %s out, %d turns, %d%% locate, %d s wall"
                 % (len(agents), runs, "" if runs == 1 else "s", k(total_in), k(total_distinct), k(total_out),
                    total_turns, share(total_locate, total_turns), wall))
    return lines


def k(n):
    return "%dk" % round(n / 1000) if n >= 1000 else str(n)
