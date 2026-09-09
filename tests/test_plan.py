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


PIN = "http GET http://127.0.0.1:${PORT_API}/export.csv 200 rows = 3"


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
            (PLAN.replace("depends_on: none", "depends_on: st-09"), "line 7: depends on 'st-09' which is not a sub-task in this plan"),
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

    def test_gaps_carry_the_answer_or_are_refused(self):
        gaps = self.ws / "product/features/hello/spec-gaps.md"
        gaps.write_text("# hello\n\n## Which delimiter wins\nAssumed: comma, the common case\nAffects: st-01\nPinned: st-01 %s\n\n## Empty export\nAffects: st-01\nPinned: st-01 lint\n" % PIN)
        done = plan(self.ws, PLAN)
        self.assertEqual(done.returncode, 1)
        self.assertIn("spec-gaps.md entry has no 'Assumed:' line", done.stderr)
        self.assertIn("\n  ## Empty export", done.stderr)
        self.assertNotIn("Which delimiter", done.stderr)
        gaps.write_text("# hello\n\n## Which delimiter wins\nAssumed: comma, the common case\nAffects: st-01\nPinned: st-01 %s\n" % PIN)
        done = plan(self.ws, PLAN)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["gaps"],
                         [{"question": "Which delimiter wins", "assumed": "comma, the common case", "affects": "st-01", "pinned": "st-01 " + PIN}])
        self.assertNotIn("criteria_text", done.stdout, "the raw criteria resolve the gaps here and go no further")

    def test_an_answer_pinned_to_no_criterion_is_refused_at_parse(self):
        gaps = self.ws / "product/features/hello/spec-gaps.md"
        entry = "# hello\n\n## Which delimiter wins\nAssumed: comma, the common case\nAffects: st-01\nPinned: %s\n"
        for pin in ["st-01 http GET http://127.0.0.1:${PORT_API}/export.csv 200 rows = 4",  # a criterion the plan does not carry
                    "st-02 lint",                                                           # a criterion of another sub-task
                    "st-09 lint",                                                           # a sub-task that does not exist
                    "lint"]:                                                                # no sub-task at all
            gaps.write_text(entry % pin)
            done = plan(self.ws, PLAN)
            self.assertEqual(done.returncode, 1, pin)
            self.assertIn("'Pinned:' names no criterion in plan.md", done.stderr, pin)
            self.assertIn("\n  Pinned: %s" % pin, done.stderr, pin)
        gaps.write_text(entry % ("st-01 " + PIN))
        self.assertEqual(plan(self.ws, PLAN).returncode, 0)

    def test_a_subtask_that_is_really_several_is_refused(self):
        for text, expected in [
            # a sixth criterion on st-01
            (PLAN.replace("- lint\n", "- lint\n- typecheck\n- browser web/export.spec.js\n- test api/test_rows.py\n", 1),
             "line 15: sub-task carries 6 criteria, past 5"),
            # two stacks named on one sub-task
            (PLAN.replace("stack: api\nfiles: repos/svc/export.py", "stack: api, web\nfiles: repos/svc/export.py"),
             "line 5: a sub-task runs in one stack"),
            # one stack named, a file reached in another stack's repo
            (PLAN.replace("files: repos/svc/export.py, repos/svc/routes.py", "files: repos/svc/export.py, repos/web/orders.js"),
             "line 6: file 'repos/web/orders.js' is outside repos/svc, the repo of stack 'api': a sub-task runs in one stack"),
            # st-01 waits on st-02, which waits on st-01
            (PLAN.replace("depends_on: none", "depends_on: st-02"), "line 4: dependency cycle: st-01 > st-02 > st-01"),
            # a cycle no line of the file shows in order: st-03 waits on st-02, which the plan already has waiting on st-01
            (PLAN.replace("## st-01 · Orders export as CSV through the API\nstack: api\nfiles: repos/svc/export.py, repos/svc/routes.py\ndepends_on: none",
                          "## st-01 · Orders export as CSV through the API\nstack: api\nfiles: repos/svc/export.py, repos/svc/routes.py\ndepends_on: st-03"),
             "dependency cycle:"),
        ]:
            done = plan(self.ws, text)
            self.assertEqual(done.returncode, 1, expected)
            self.assertIn(expected, done.stderr, expected)
        self.assertEqual(plan(self.ws, PLAN).returncode, 0, "the plan itself is fine")

    def test_a_dependency_may_be_declared_before_the_sub_task_that_carries_it(self):
        forward = PLAN.replace("## st-01 · Orders export as CSV through the API\nstack: api\nfiles: repos/svc/export.py, repos/svc/routes.py\ndepends_on: none",
                               "## st-01 · Orders export as CSV through the API\nstack: api\nfiles: repos/svc/export.py, repos/svc/routes.py\ndepends_on: st-03")
        forward = forward.replace("## st-03 · Each row carries a one-line summary\nstack: api\nfiles: repos/svc/summarize.py\ndepends_on: st-01, st-02",
                                  "## st-03 · Each row carries a one-line summary\nstack: api\nfiles: repos/svc/summarize.py\ndepends_on: none")
        done = plan(self.ws, forward)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["subtasks"][0]["depends_on"], ["st-03"])

    def test_a_screen_feature_without_a_visual_check_is_refused_unless_declared(self):
        config = self.ws / "product/client.config.yaml"
        original = config.read_text()
        ui = PLAN.replace("kind: service", "kind: mixed")
        done = plan(self.ws, ui)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["comparable"])
        without = ui.replace("- visual export-button design/orders.png\n", "")
        done = plan(self.ws, without)
        self.assertEqual(done.returncode, 1)
        self.assertIn("kind mixed activates the visual diff and no sub-task carries a visual criterion", done.stderr)
        self.assertIn("design.comparable: false", done.stderr)
        self.assertEqual(plan(self.ws, without.replace("kind: mixed", "kind: service")).returncode, 0, "a service feature has no screen to compare")
        config.write_text(original + "design:\n  comparable: false\n")
        done = plan(self.ws, without)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(json.loads(done.stdout)["comparable"])
        done = plan(self.ws, ui)
        self.assertEqual(done.returncode, 1)
        self.assertIn("design.comparable: false, so nothing can be compared against", done.stderr)
        self.assertIn("\n  - visual export-button", done.stderr)
        config.write_text(original)

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
