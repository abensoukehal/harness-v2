import json
import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run

PLAN = """# hello
kind: service

## st-01 · Orders export as CSV through the API
stack: api
files: repos/svc/export.py, repos/svc/routes.py
depends_on: none
line_budget: 80
criteria:
- test api/test_export.py
- http GET http://127.0.0.1:${PORT_API}/export.csv 200 rows = 3
- lint

## st-02 · The export shows in the orders screen
stack: web
files: repos/web/orders.js
depends_on: st-01
line_budget: 40
criteria:
- browser web/export.spec.js
- visual export-button design/orders.png
- log api present export requested
- typecheck

## st-03 · Each row carries a one-line summary
stack: api
files: repos/svc/summarize.py
depends_on: st-01, st-02
line_budget: 60
criteria:
- examples api/summaries.json 0.9
"""


def plan(ws, text):
    (ws / "product/features/hello/plan.md").write_text(text)
    return run("plan", "hello", ws=ws)


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))

    def test_valid_plan_becomes_state_subtasks(self):
        done = plan(self.ws, PLAN)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["kind"], "service")
        ids = [s["id"] for s in out["subtasks"]]
        self.assertEqual(ids, ["st-01", "st-02", "st-03"])
        first = out["subtasks"][0]
        self.assertEqual(first["files"], ["repos/svc/export.py", "repos/svc/routes.py"])
        self.assertEqual(first["depends_on"], [])
        self.assertEqual((first["status"], first["attempts"], first["interruptions"], first["line_budget"], first["role"]), ("pending", 0, 0, 80, "backend"))
        self.assertEqual(first["worktree"], ".worktrees/hello/svc")
        self.assertEqual(out["subtasks"][1]["worktree"], ".worktrees/hello/web")
        self.assertEqual(first["exit_criteria"][1], {"kind": "http", "method": "GET", "url": "http://127.0.0.1:${PORT_API}/export.csv",
                                                     "expect_status": 200, "json_path": "rows", "value": "3"})
        second = out["subtasks"][1]
        self.assertEqual(second["role"], "frontend")
        self.assertEqual(second["depends_on"], ["st-01"])
        self.assertEqual(second["exit_criteria"][2], {"kind": "log", "stack": "api", "present": True, "pattern": "export requested"})
        self.assertEqual(out["subtasks"][2]["exit_criteria"], [{"kind": "examples", "set": "api/summaries.json", "floor": 0.9}])
        self.assertEqual(out["config"]["stacks"], {"api": {"repo": "svc", "role": "backend"}, "web": {"repo": "web", "role": "frontend"},
                                                   "db": {"repo": None, "role": "backend"}})
        self.assertEqual((out["config"]["max_fixes"], out["config"]["mode"], out["config"]["branch_prefix"]), (3, "pr", "feature/"))

    def test_malformed_plans_quote_the_line(self):
        cases = [
            (PLAN.replace("kind: service\n", ""), "missing 'kind"),
            (PLAN.replace("kind: service", "kind: fullstack"), "line 2: kind must be one of"),
            (PLAN.replace("stack: web", "stack: mobile"), "line 15: unknown stack 'mobile'"),
            (PLAN.replace("stack: web", "stack: db"), "line 15: stack 'db' has no repo"),
            (PLAN.replace("line_budget: 40\n", ""), "line 14: missing field 'line_budget'"),
            (PLAN.replace("- lint", "- manual looks correct"), "line 12: not a criterion"),
            (PLAN.replace("0.9", "1"), "line 31: examples floor must be"),
            (PLAN.replace("depends_on: none", "depends_on: st-02"), "line 7: depends on 'st-02' which is not an earlier"),
            (PLAN.replace("## st-03", "## st-01"), "line 25: duplicate sub-task id"),
            (PLAN.replace("- examples api/summaries.json 0.9\n", ""), "line 25: sub-task has no criterion"),
            (PLAN.replace("- http GET", "- http FETCH"), "line 11: http method must be"),
            (PLAN.replace("## st-02 · The", "## st-02 - The"), "line 14: sub-task heading must read"),
            (PLAN.replace("files: repos/web/orders.js", "owner: web"), "line 16: unknown field 'owner'"),
            (PLAN.replace("- log api present", "- log cache present"), "line 22: log criterion names unknown stack 'cache'"),
        ]
        for text, expected in cases:
            done = plan(self.ws, text)
            self.assertEqual(done.returncode, 1, expected)
            self.assertIn(expected, done.stderr, expected)
            self.assertIn("\n  ", done.stderr, "the offending line is quoted")

    def test_a_verb_with_no_command_behind_it_is_refused_at_parse(self):
        config = self.ws / "product/client.config.yaml"
        original = config.read_text()
        for gone in ["browser_runner:\n  web: playwright test\n", "api: pytest, ", "      lint: \"true\"\n", "      typecheck: \"true\"\n",
                     "visual:\n  threshold_pct: 2.0\n  viewport: 1440x900\n  max_attempts: 4\n"]:
            self.assertIn(gone, original)
        cases = [
            ("browser_runner:\n  web: playwright test\n", "- browser web/export.spec.js", "criterion 'browser' needs browser_runner.web in the config"),
            ("api: pytest, ", "- test api/test_export.py", "criterion 'test' needs test_runner.api in the config"),
            ("      lint: \"true\"\n", "- lint", "criterion 'lint' needs stacks.api.commands.lint in the config"),
            ("      typecheck: \"true\"\n", "- typecheck", "criterion 'typecheck' needs stacks.web.commands.typecheck in the config"),
            ("visual:\n  threshold_pct: 2.0\n  viewport: 1440x900\n  max_attempts: 4\n", "- visual export-button design/orders.png", "criterion 'visual' needs visual.threshold_pct in the config"),
        ]
        for gone, offending, message in cases:
            config.write_text(original.replace(gone, ""))
            done = plan(self.ws, PLAN)
            self.assertEqual(done.returncode, 1, offending)
            self.assertIn(message, done.stderr, offending)
            self.assertIn("\n  " + offending, done.stderr, offending)
        config.write_text(original)
        self.assertEqual(plan(self.ws, PLAN).returncode, 0)

    def test_twenty_one_subtasks_refused(self):
        blocks = "".join("\n## st-%02d · Step %d\nstack: api\nfiles: a.py\ndepends_on: none\nline_budget: 1\ncriteria:\n- lint\n" % (i, i) for i in range(1, 22))
        done = plan(self.ws, "# hello\nkind: service\n" + blocks)
        self.assertEqual(done.returncode, 1)
        self.assertIn("more than 20 sub-tasks", done.stderr)
        self.assertIn("## st-21", done.stderr)

    def test_missing_plan(self):
        done = run("plan", "hello", ws=self.ws)
        self.assertEqual(done.returncode, 1)
        self.assertIn("/harness-plan hello", done.stderr)
