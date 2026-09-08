import shutil
import subprocess

from . import HARNESS_ROOT, HarnessError, git

HOOK = HARNESS_ROOT / "hooks" / "pre-push"


def configure_repo(ws, cfg, repo_dir):
    """Fixed identity, no signing, harness-owned hooks (9.2, 9.4). Repo-level, so every worktree inherits it."""
    hooks = ws / ".hooks"
    hooks.mkdir(exist_ok=True)
    shutil.copy(HOOK, hooks / "pre-push")
    (hooks / "pre-push").chmod(0o755)
    author = cfg["delivery"]["commit_author"]
    for key, value in [("user.name", author["name"]), ("user.email", author["email"]),
                       ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))]:
        git("config", "--local", key, value, cwd=repo_dir)


def repos_of(cfg):
    return sorted({s["repo"] for s in cfg["stacks"].values() if s["repo"] is not None})


def registered(repo_dir):
    out = git("worktree", "list", "--porcelain", cwd=repo_dir)
    return {line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")}


def ensure(ws, cfg, slug, state):
    """One worktree per repo the config names, on the feature branch (11.2). Idempotent."""
    branch = cfg["delivery"]["branch_prefix"] + slug
    base = cfg["delivery"]["base_branch"]
    for repo in repos_of(cfg):
        repo_dir = ws / "repos" / repo
        if not (repo_dir / ".git").exists():
            raise HarnessError("repos/%s is not a git checkout" % repo)
        configure_repo(ws, cfg, repo_dir)
        rel = ".worktrees/%s/%s" % (slug, repo)
        path = ws / rel
        if str(path.resolve()) not in {str(p) for p in map(lambda x: (ws / x).resolve(), registered(repo_dir))}:
            if path.exists():
                raise HarnessError("%s exists but is not a registered worktree of repos/%s" % (rel, repo))
            path.parent.mkdir(parents=True, exist_ok=True)
            have_branch = subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "refs/heads/" + branch],
                cwd=repo_dir, capture_output=True).returncode == 0
            target = [branch] if have_branch else ["-b", branch, base]
            git("worktree", "add", str(path), *target, cwd=repo_dir)
        state["worktrees"][repo] = rel
    state["branch"] = branch


def remove(ws, cfg, slug, state):
    """Drop the feature's worktrees, keep the branches (10.1)."""
    for repo in repos_of(cfg):
        path = ws / ".worktrees" / slug / repo
        repo_dir = ws / "repos" / repo
        if path.exists():
            git("worktree", "remove", "--force", str(path), cwd=repo_dir)
        if (repo_dir / ".git").exists():
            git("worktree", "prune", cwd=repo_dir)
    shutil.rmtree(ws / ".worktrees" / slug, ignore_errors=True)
    state["worktrees"] = {}
