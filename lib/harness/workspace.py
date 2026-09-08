"""bin/init, bin/link, bin/new."""
import os
import shutil
import subprocess

from . import HARNESS_ROOT, HarnessError, check_slug, git

TEMPLATES = HARNESS_ROOT / "templates"
LINKED = ["workflows", "agents", "skills"]
COST_LOG_HEADER = "slug | tokens | wall_time_s | subtasks | blocked\n"


def render(template, **subs):
    text = (TEMPLATES / template).read_text()
    for key, value in subs.items():
        text = text.replace("<%s>" % key, value)
    return text


def init(client, root):
    check_slug(client, "client name")
    ws = root / client
    if ws.exists():
        raise HarnessError("%s already exists" % ws)
    for d in ["secrets", "repos", ".worktrees", "product/code-map", "product/tests", "product/features"]:
        (ws / d).mkdir(parents=True)
    os.chmod(ws / "secrets", 0o700)
    (ws / "CLAUDE.md").write_text(render("workspace/CLAUDE.md", client=client))
    product = ws / "product"
    (product / "client.config.yaml").write_text(render("workspace/client.config.yaml", client=client))
    (product / "conventions.md").write_text("")
    (product / "cost-log.md").write_text(COST_LOG_HEADER)
    for d in ["code-map", "tests", "features"]:
        (product / d / ".gitkeep").write_text("")
    git("init", "-q", cwd=product)
    git("clone", "-q", str(HARNESS_ROOT), str(ws / "harness"))
    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=HARNESS_ROOT, capture_output=True, text=True)
    if origin.returncode == 0:
        git("remote", "set-url", "origin", origin.stdout.strip(), cwd=ws / "harness")
    link(ws)
    return ws


def link(ws):
    source = ws / "harness" / "claude"
    if not source.is_dir():
        raise HarnessError("%s has no harness/claude directory" % ws)
    dot = ws / ".claude"
    dot.mkdir(exist_ok=True)
    for name in LINKED:
        target = dot / name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            raise HarnessError("%s is a real directory, not a link" % target)
        target.symlink_to(os.path.join("..", "harness", "claude", name))


def new(ws, slug):
    check_slug(slug)
    folder = ws / "product" / "features" / slug
    if folder.exists():
        raise HarnessError("feature %s already exists at %s" % (slug, folder))
    (folder / "design").mkdir(parents=True)
    (folder / "spec.md").write_text(render("feature/spec.md", slug=slug))
    return folder
