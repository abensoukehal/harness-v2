"""bin/init, bin/link, bin/new."""
import json
import os
import shutil
import subprocess
import sys

from . import HARNESS_ROOT, PIN, HarnessError, check_pin, check_slug, git
from .config import load_config
from .worktree import repos_of

TEMPLATES = HARNESS_ROOT / "templates"
LINKED = ["workflows", "agents", "skills"]
COST_LOG_HEADER = "slug | tokens | wall_time_s | subtasks | blocked\n"


def render(template, **subs):
    text = (TEMPLATES / template).read_text()
    for key, value in subs.items():
        text = text.replace("<%s>" % key, value)
    return text


def init(client, root, config=None, out=sys.stdout):
    """A workspace from the template: harness clone at the pin with its dependencies installed, the config, every repo it names (2.1)."""
    check_slug(client, "client name")
    ws = root / client
    if ws.exists():
        raise HarnessError("%s already exists" % ws)
    if config is not None and not config.is_file():
        raise HarnessError("no config file at %s" % config)
    for d in ["secrets", "repos", ".worktrees", "product/code-map", "product/tests", "product/features"]:
        (ws / d).mkdir(parents=True)
    os.chmod(ws / "secrets", 0o700)
    (ws / "CLAUDE.md").write_text(render("workspace/CLAUDE.md", client=client, root=str(ws)))
    product = ws / "product"
    (product / "client.config.yaml").write_text(config.read_text() if config else render("workspace/client.config.yaml", client=client))
    (product / "conventions.md").write_text("")
    (product / "cost-log.md").write_text(COST_LOG_HEADER)
    for d in ["code-map", "tests", "features"]:
        (product / d / ".gitkeep").write_text("")
    git("init", "-q", cwd=product)
    git("clone", "-q", str(HARNESS_ROOT), str(ws / "harness"))
    origin = subprocess.run(["git", "remote", "get-url", "origin"], cwd=HARNESS_ROOT, capture_output=True, text=True)
    if origin.returncode == 0:
        git("remote", "set-url", "origin", origin.stdout.strip(), cwd=ws / "harness")
    (ws / PIN).write_text(git("rev-parse", "HEAD", cwd=ws / "harness") + "\n")
    install_harness(ws / "harness")
    if config:
        clone_repos(ws, load_config(ws), strict=True, out=out)
    link(ws, out)
    return ws


def install_harness(tree):
    done = subprocess.run(["npm", "ci", "--no-fund", "--no-audit", "--prefer-offline"], cwd=tree, capture_output=True, text=True)
    if done.returncode:
        raise HarnessError("harness dependencies did not install:\n%s" % "\n".join(done.stderr.splitlines()[-10:]))


def clone_repos(ws, cfg, strict, out=sys.stdout):
    """Every repo a stack names exists under repos/, cloned from repos.<name> in the config. Missing with no url: refused when strict, named otherwise."""
    urls = cfg.get("repos", {})
    for repo in repos_of(cfg):
        target = ws / "repos" / repo
        if (target / ".git").exists():
            continue
        if repo not in urls:
            if strict:
                raise HarnessError("repos/%s is missing and the config has no url under repos.%s" % (repo, repo))
            out.write("repos/%s is missing and the config has no url under repos.%s\n" % (repo, repo))
            continue
        git("clone", "-q", urls[repo], str(target))
        out.write("cloned repos/%s\n" % repo)


def link(ws, out=sys.stdout):
    """Link .claude/ to the harness, write the workspace root into .claude/settings.json, the one place every agent reads it from (2.2),
    and clone any repo the config names that is not there yet."""
    source = ws / "harness" / "claude"
    if not source.is_dir():
        raise HarnessError("%s has no harness/claude directory" % ws)
    check_pin(ws)
    clone_repos(ws, load_config(ws), strict=False, out=out)
    dot = ws / ".claude"
    dot.mkdir(exist_ok=True)
    settings_path = dot / "settings.json"
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    settings.setdefault("env", {})["HARNESS_WORKSPACE"] = str(ws)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    for name in LINKED:
        target = dot / name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            raise HarnessError("%s is a real directory, not a link" % target)
        target.symlink_to(os.path.join("..", "harness", "claude", name))


def pin(ws, commit=None):
    """Move harness/ to a commit (default: the remote's HEAD) and record it in product/harness.pin."""
    harness = ws / "harness"
    if not (harness / ".git").exists():
        raise HarnessError("%s has no harness checkout" % ws)
    fetched = subprocess.run(["git", "fetch", "-q", "origin"], cwd=harness, capture_output=True, text=True)
    if commit is None:
        if fetched.returncode:
            raise HarnessError("cannot fetch the harness remote: %s" % fetched.stderr.strip())
        head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/HEAD"], cwd=harness, capture_output=True, text=True)
        if head.returncode:
            head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/main"], cwd=harness, capture_output=True, text=True)
        if head.returncode:
            raise HarnessError("the harness remote has no HEAD or main to pin to; pass a commit")
        commit = head.stdout.strip()
    sha = git("rev-parse", "--verify", commit + "^{commit}", cwd=harness)
    git("checkout", "-q", "--detach", sha, cwd=harness)
    (ws / PIN).write_text(sha + "\n")
    return sha


def new(ws, slug):
    check_slug(slug)
    folder = ws / "product" / "features" / slug
    if folder.exists():
        raise HarnessError("feature %s already exists at %s" % (slug, folder))
    (folder / "design").mkdir(parents=True)
    (folder / "spec.md").write_text(render("feature/spec.md", slug=slug))
    return folder
