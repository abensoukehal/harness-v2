"""Cost from the runtime's own transcripts (6.2): input tokens per agent, not output deltas. One record per agent, keyed by agent id."""
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from . import HarnessError
from .config import load_state, save_state

ROLES = {"workflow-subagent": "io"}


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
            turns += 1
        stamp = e.get("timestamp")
        if stamp:
            start = start or stamp
            end = stamp
    if first is None or not re.search(r"%s(?![\w-])" % re.escape(str(ws)), first) or not re.search(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(slug), first):
        return None
    out = {"role": role, "run": path.parent.name, "tokens_in": tokens_in, "tokens_out": tokens_out, "turns": turns,
           "duration_s": int(seconds(end) - seconds(start)) if start and end else 0}
    m = re.search(r"\bst-[0-9]{2,}\b", first[:400])
    if m:
        out["subtask"] = m.group(0)
    return out, (seconds(start) if start else None, seconds(end) if end else None)


def cost(ws, slug, dirs=None, out=sys.stdout):
    state = load_state(ws, slug)
    agents = state.setdefault("cost_by_agent", {})
    spans = {}
    for d in transcript_dirs(dirs):
        for path in sorted(d.glob("agent-*.jsonl")):
            found = record(path, slug, ws)
            if found:
                agents[path.stem[len("agent-"):]], span = found
                spans.setdefault(d.name, []).append(span)
    by_id = {s["id"]: s for s in state["subtasks"]}
    for st in by_id.values():
        mine = [a for a in agents.values() if a.get("subtask") == st["id"]]
        if not mine:
            continue
        c = st.setdefault("cost", {"tokens_in": 0, "tokens_out": 0, "duration_s": 0, "lines_added": 0})
        c["tokens_in"] = sum(a["tokens_in"] for a in mine)
        c["tokens_out"] = sum(a["tokens_out"] for a in mine)
        c["duration_s"] = c["duration_s"] or sum(a["duration_s"] for a in mine)
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


def summary(agents, wall):
    roles = {}
    for a in agents.values():
        r = roles.setdefault(a["role"], [0, 0, 0])
        r[0] += a["tokens_in"]
        r[1] += a["tokens_out"]
        r[2] += 1
    lines = ["%s: %d agents, %s in, %s out" % (role, n, k(i), k(o)) for role, (i, o, n) in sorted(roles.items(), key=lambda kv: -kv[1][0])]
    total_in = sum(a["tokens_in"] for a in agents.values())
    total_out = sum(a["tokens_out"] for a in agents.values())
    runs = len({a.get("run") for a in agents.values() if a.get("run")})
    lines.append("total: %d agents over %d run%s, %s in, %s out, %d s wall" % (len(agents), runs, "" if runs == 1 else "s", k(total_in), k(total_out), wall))
    return lines


def k(n):
    return "%dk" % round(n / 1000) if n >= 1000 else str(n)
