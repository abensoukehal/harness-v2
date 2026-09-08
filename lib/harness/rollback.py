"""Return the engine to an earlier retro tag with a revert commit (14.5)."""
import subprocess

from . import HarnessError, git


def is_ancestor(a, b, cwd):
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=cwd, capture_output=True).returncode == 0


def previous_tag(root):
    head = git("rev-parse", "HEAD", cwd=root)
    for tag in git("tag", "-l", "retro/*", "--sort=-creatordate", cwd=root).split():
        sha = git("rev-parse", tag + "^{commit}", cwd=root)
        if sha != head and is_ancestor(sha, head, root):
            return tag
    raise HarnessError("no retro/* tag behind HEAD to roll back to")


def rollback(root, tag=None):
    if git("status", "--porcelain", cwd=root):
        raise HarnessError("working tree is not clean; commit or stash first")
    tag = tag or previous_tag(root)
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", tag + "^{commit}"], cwd=root, capture_output=True).returncode:
        raise HarnessError("no such tag: %s" % tag)
    commits = git("log", "--format=%h %s", "%s..HEAD" % tag, cwd=root).splitlines()
    if not commits:
        raise HarnessError("HEAD is already at %s" % tag)
    try:
        git("revert", "--no-commit", "%s..HEAD" % tag, cwd=root)
    except HarnessError as e:
        subprocess.run(["git", "revert", "--abort"], cwd=root, capture_output=True)
        raise HarnessError("revert conflicts, nothing changed:\n%s" % e)
    questions = root / "OPEN_QUESTIONS.md"
    text = questions.read_text() if questions.exists() else "# Open questions\n"
    entry = "\n## Rolled back to %s\n\nIntent that did not survive:\n%s\nNot retried until this is decided.\n" % (
        tag, "".join("- %s\n" % c for c in commits))
    questions.write_text(text + entry)
    git("add", "OPEN_QUESTIONS.md", cwd=root)
    git("commit", "-q", "-m", "Roll back engine to %s" % tag, cwd=root)
    return tag, commits


def tag_push(root, slug):
    """Tag HEAD retro/<slug>, push the branch, then the tag. A refused branch push deletes the tag (14.5)."""
    tag = "retro/" + slug
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    if branch == "HEAD":
        raise HarnessError("detached HEAD: check out the branch to push first")
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", "refs/tags/" + tag], cwd=root, capture_output=True).returncode == 0:
        raise HarnessError("tag %s exists; one retro tag per feature" % tag)
    git("tag", tag, cwd=root)
    pushed = subprocess.run(["git", "push", "origin", branch], cwd=root, capture_output=True, text=True)
    if pushed.returncode:
        git("tag", "-d", tag, cwd=root)
        raise HarnessError("push of %s refused; tag %s deleted locally, nothing reached the remote:\n%s" % (branch, tag, pushed.stderr.strip()))
    git("push", "origin", tag, cwd=root)
    return tag
