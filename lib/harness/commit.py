"""The only way feature code reaches a client repo (9.1, 9.2)."""
import fnmatch
import os
import re

from . import HarnessError, git
from .config import load_config, load_state

DENY_NAMES = {"state.json", "plan.md", "retro.md", "spec-gaps.md", "journey.md", "decisions.md", "CLAUDE.md"}
DENY_GLOBS = ["*.harness.*", ".env", "*.env"]
DENY_PARTS = {".claude", "product", ".worktrees", "harness", "secrets"}
INTERNAL = ["state.json", "plan.md", "retro.md", "decisions.md", "spec-gaps.md", "journey.md", "client.config.yaml",
            "conventions.md", "code-map", ".claude", "product/", ".worktrees", "harness/"]
PATTERNS = [
    ("sub-task id", re.compile(r"\bst-[0-9]{2,}\b")),
    ("ticket id", re.compile(r"\b(?!(?:UTF|SHA|ISO|RFC)-)[A-Z]{2,}-[0-9]+\b")),
    ("date", re.compile(r"\b[0-9]{4}-[0-9]{2}-[0-9]{2}\b")),
    ("forbidden word", re.compile(r"\b(harness|agents?|claude)\b", re.I)),
    ("forbidden word", re.compile(r"\bAI\b")),
]
TRAILER = re.compile(r"^(Co-Authored-By|Signed-off-by):", re.I | re.M)
SUBJECT_MAX = 72


def refused_path(rel):
    parts = rel.split("/")
    name = parts[-1]
    if name in DENY_NAMES:
        return "harness or product file"
    for glob in DENY_GLOBS:
        if fnmatch.fnmatch(name, glob):
            return "matches " + glob
    hit = DENY_PARTS & set(parts)
    if hit:
        return "under " + sorted(hit)[0] + "/"
    return None


def changed_paths(wt):
    entries = iter(git("status", "--porcelain", "-z", "--untracked-files=all", cwd=wt).split("\0"))
    paths = []
    for entry in entries:
        if not entry:
            continue
        xy, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in xy or "C" in xy:
            next(entries, None)
    return paths


def check_paths(wt, paths):
    root = str(wt.resolve()) + "/"
    refused = []
    for rel in paths:
        reason = refused_path(rel)
        if reason is None and not str((wt / rel).resolve()).startswith(root):
            reason = "outside the worktree"
        if reason:
            refused.append("%s: %s" % (rel, reason))
    return refused


def check_message(message, slugs):
    problems = []
    lines = message.split("\n")
    subject = lines[0]
    if not subject.strip():
        problems.append("empty subject")
    if len(subject) > SUBJECT_MAX:
        problems.append("subject longer than %d characters" % SUBJECT_MAX)
    if len(lines) > 1 and lines[1].strip():
        problems.append("subject must be one line, then a blank line, then the body")
    for label, rx in PATTERNS:
        m = rx.search(message)
        if m:
            problems.append("%s %r" % (label, m.group(0)))
    lowered = message.lower()
    for slug in sorted(slugs):
        if re.search(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(slug), lowered):
            problems.append("feature slug %r" % slug)
    for name in INTERNAL:
        if name.lower() in lowered:
            problems.append("internal file %r" % name)
    return problems


def commit(ws, slug, repo, subject, body=None):
    cfg = load_config(ws)
    state = load_state(ws, slug)
    wt = ws / ".worktrees" / slug / repo
    if not (wt / ".git").exists():
        raise HarnessError("no worktree at .worktrees/%s/%s; run up or resume first" % (slug, repo))
    head = git("rev-parse", "--abbrev-ref", "HEAD", cwd=wt)
    if head != state["branch"]:
        raise HarnessError("worktree is on %s, feature branch is %s" % (head, state["branch"]))
    paths = changed_paths(wt)
    if not paths:
        raise HarnessError("nothing to commit in .worktrees/%s/%s" % (slug, repo))
    refused = check_paths(wt, paths)
    if refused:
        raise HarnessError("refused paths, nothing committed:\n  " + "\n  ".join(refused))
    message = subject + ("\n\n" + body.strip() + "\n" if body else "")
    features = ws / "product" / "features"
    slugs = {slug} | {p.name for p in features.iterdir() if p.is_dir()}
    problems = check_message(message, slugs)
    if problems:
        raise HarnessError("refused message, nothing committed:\n  " + "\n  ".join(problems))
    author = cfg["delivery"]["commit_author"]
    env = dict(os.environ, GIT_AUTHOR_NAME=author["name"], GIT_AUTHOR_EMAIL=author["email"],
               GIT_COMMITTER_NAME=author["name"], GIT_COMMITTER_EMAIL=author["email"])
    hooks = ws / ".hooks"
    git("add", "-A", cwd=wt)
    git("-c", "core.hooksPath=" + str(hooks), "-c", "commit.gpgsign=false", "commit", "-q", "-m", message, cwd=wt, env=env)
    sha, an, ae, cn, ce = git("log", "-1", "--format=%H%n%an%n%ae%n%cn%n%ce", cwd=wt).split("\n")
    recorded = git("log", "-1", "--format=%B", cwd=wt)
    wrong = []
    if (an, ae, cn, ce) != (author["name"], author["email"], author["name"], author["email"]):
        wrong.append("identity is %s <%s> / %s <%s>" % (an, ae, cn, ce))
    if TRAILER.search(recorded):
        wrong.append("a trailer was added")
    if recorded.strip() != message.strip():
        wrong.append("message was altered")
    if wrong:
        git("reset", "--soft", "HEAD~1", cwd=wt)
        raise HarnessError("commit undone: " + "; ".join(wrong))
    return sha
