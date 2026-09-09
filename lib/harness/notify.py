"""Pushed events (13.1): three events, Telegram, never blocking."""
import json
import os
import urllib.request

from .ask import render
from .config import feature_dir, load_config, load_state, save_state
from .report import build_report, relative

EVENTS = ("plan_ready", "run_finished", "needs_answer")


def message_for(ws, slug, event, state):
    if event == "run_finished":
        report = feature_dir(ws, slug) / "report.md"
        return report.read_text() if report.exists() else build_report(ws, slug)
    if event == "plan_ready":
        return relative(state.get("plan_message") or "Plan ready for %s: product/features/%s/plan.md" % (slug, slug), ws)
    asks = [s["ask"] for s in state["subtasks"] if s.get("ask")]
    return relative("\n".join(render(a) for a in asks), ws) if asks else "No question is pending for %s." % slug


def notify(ws, slug, event, out):
    cfg = load_config(ws)
    if event not in EVENTS or event not in cfg["notify"]["events"]:
        out.write("event %s is not pushed: not one of %s\n" % (event, ", ".join(cfg["notify"]["events"])))
        return False
    state = load_state(ws, slug)
    text = message_for(ws, slug, event, state)
    url = os.environ.get("HARNESS_TELEGRAM_URL")
    chat_file = ws / "secrets" / cfg["notify"]["telegram"]["chat_id_ref"]
    token_file = ws / "secrets" / "telegram_bot_token"
    chat = chat_file.read_text().strip() if chat_file.exists() else None
    if not url:
        if not token_file.exists() or not chat:
            return friction(ws, slug, state, event, "no telegram credentials in secrets/", out)
        url = "https://api.telegram.org/bot%s/sendMessage" % token_file.read_text().strip()
    body = json.dumps({"chat_id": chat or "unset", "text": text}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            if not 200 <= r.status < 300:
                return friction(ws, slug, state, event, "telegram answered %d" % r.status, out)
    except Exception as e:
        return friction(ws, slug, state, event, str(e).split("\n")[0][:120], out)
    out.write("%s sent\n" % event)
    return True


def friction(ws, slug, state, event, why, out):
    state["frictions"].append("notify · %s not sent · %s" % (event, why))
    save_state(ws, slug, state)
    out.write("%s not sent: %s (recorded as a friction)\n" % (event, why))
    return False
