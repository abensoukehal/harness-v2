import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run
from harness import HarnessError
from harness.briefing import assemble
from harness.config import load_state, save_state

CONVENTIONS = """# Conventions

## all
- Errors bubble up as typed exceptions.

## api
- Handlers return plain dicts.

## web
- Components live next to their styles.
"""


def subtask(id_, stack, repo, criteria, **extra):
    base = {"id": id_, "stack": stack, "status": "pending", "attempts": 0, "interruptions": 0,
            "worktree": ".worktrees/hello/" + repo, "exit_criteria": criteria}
    base.update(extra)
    return base


class Briefing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        (self.ws / "product/conventions.md").write_text(CONVENTIONS)
        state = load_state(self.ws, "hello")
        state["ports"] = {"api": 50100, "web": 50101, "db": 50102}
        state["subtasks"] = [
            subtask("st-01", "api", "svc", [
                {"kind": "http", "method": "GET", "url": "http://127.0.0.1:${PORT_API}/export", "expect_status": 200, "json_path": "rows", "value": "3"},
                {"kind": "log", "stack": "api", "present": True, "pattern": "export requested"},
                {"kind": "lint"}],
                goal="Orders export as CSV", files=["repos/svc/export.py", "repos/svc/lib/csv.py"], line_budget=60),
            subtask("st-02", "web", "web", [{"kind": "browser", "script": "web/ONLY-IN-ST02.spec.js"}], depends_on=["st-01"]),
            subtask("st-03", "api", "svc", [{"kind": "examples", "set": "api/summaries.json", "floor": 0.9}], depends_on=["st-01"], token_budget=777),
        ]
        save_state(self.ws, "hello", state)

    def test_one_subtask_and_nothing_more(self):
        text = assemble(self.ws, "hello", "st-01")
        for line in ["# Mission st-01 · Orders export as CSV", "feature: hello   branch: feature/hello", "stack: api (backend)",
                     "work in: %s" % (self.ws / ".worktrees/hello/svc"), "  %s" % (self.ws / ".worktrees/hello/svc/export.py"), "  %s" % (self.ws / ".worktrees/hello/svc/lib/csv.py"),
                     "depends on this: st-02, st-03", "line budget: 60      token budget: 33333",
                     "## Exit criteria", "- http GET http://127.0.0.1:50100/export 200, rows = 3", '- log api present "export requested"', "- lint",
                     "## Stack", "test runner: pytest", "ports: PORT_API=50100 PORT_DB=50102 PORT_WEB=50101",
                     "log: %s" % (self.ws / ".run/hello/api.log"), "## Conventions", "### all", "Errors bubble up", "### api", "Handlers return plain dicts",
                     "## Rules", "Never start or stop a stack: return restart instead."]:
            self.assertIn(line, text, line)
        for absent in ["ONLY-IN-ST02", "browser", "examples", "## Behaviour contract", "Components live next to", "install:", "dev:", "abcd1234", "hunter2", "repos/svc/export.py"]:
            self.assertNotIn(absent, text, absent)
        for line in ["## Paths, absolute; resolve none yourself",
                     "safety net, never edited: %s" % (self.ws / "product/tests"),
                     "decisions to append to: %s" % (self.ws / "product/features/hello/decisions.md")]:
            self.assertIn(line, text, line)
        self.assertEqual([l for l in text.splitlines() if " product/" in l or l.startswith(("  product/", "  repos/", "  .worktrees/"))], [],
                         "no relative path an agent has to resolve")
        self.assertLess(text.index("## Exit criteria"), text.index("## Stack"))
        self.assertTrue(text.rstrip().endswith("Prose is refused."))

    def test_behaviour_contract_only_for_examples(self):
        text = assemble(self.ws, "hello", "st-03")
        self.assertIn("## Behaviour contract", text)
        self.assertIn("set: api/summaries.json   floor: 0.9", text)
        self.assertIn("token budget: 777", text)
        self.assertNotIn("http GET", text)
        self.assertEqual(run("briefing", "hello", "st-03", ws=self.ws).stdout, text)
        missing = run("briefing", "hello", "st-09", ws=self.ws)
        self.assertEqual(missing.returncode, 1)
        self.assertIn("no sub-task st-09", missing.stderr)

    def test_largest_fixture_stays_under_the_cap(self):
        (self.ws / "product/conventions.md").write_text(
            "## all\n" + "".join("- Convention %d holds across every stack and file.\n" % i for i in range(45)) +
            "## api\n" + "".join("- Handlers follow rule %d.\n" % i for i in range(40)))
        self.assertLess(len((self.ws / "product/conventions.md").read_text()), 4000)
        text = assemble(self.ws, "hello", "st-01")
        self.assertLess(len(text), 12000)

    def test_over_the_cap_is_refused_not_truncated(self):
        (self.ws / "product/conventions.md").write_text("## api\n" + "- a long convention line that repeats itself\n" * 400)
        with self.assertRaises(HarnessError) as ctx:
            assemble(self.ws, "hello", "st-01")
        self.assertIn("cap 12000", str(ctx.exception))
        self.assertIn("conventions.md is", str(ctx.exception))
