import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run
from harness.config import load_state, save_state

CONVENTIONS = """# Conventions

## all
- Errors bubble up as typed exceptions.

## api
- Handlers return plain dicts.

## web
- Components live next to their styles.
"""


class Briefing(unittest.TestCase):
    def test_three_blocks_filtered_to_the_stack(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d))
            (ws / "product/conventions.md").write_text(CONVENTIONS)
            state = load_state(ws, "hello")
            state["ports"] = {"api": 50100, "web": 50101}
            state["subtasks"] = [
                {"id": "st-01", "stack": "api", "status": "pending", "attempts": 0, "goal": "Orders export as CSV",
                 "files": ["repos/svc/export.py"], "line_budget": 60,
                 "exit_criteria": [{"kind": "http", "method": "GET", "url": "http://127.0.0.1:${PORT_API}/export", "expect_status": 200}]},
                {"id": "st-02", "stack": "web", "status": "pending", "attempts": 0, "depends_on": ["st-01"]},
                {"id": "st-03", "stack": "api", "status": "pending", "attempts": 0, "depends_on": ["st-01"], "token_budget": 777},
            ]
            save_state(ws, "hello", state)
            done = run("briefing", "hello", "st-01", ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            text = done.stdout
            for line in ["# Technical profile", "stack: api", "directory: .worktrees/hello/svc",
                         "dev: python3 -m http.server 50100 --bind 127.0.0.1", "PORT_API=50100, PORT_WEB=50101",
                         "# Conventions", "## all", "Errors bubble up", "## api", "Handlers return plain dicts",
                         "# Mission", "goal: Orders export as CSV", "  repos/svc/export.py",
                         "- http method=GET url=http://127.0.0.1:${PORT_API}/export expect_status=200",
                         "line_budget: 60", "token_budget: 33333", "depends_on_this: st-02, st-03",
                         "No new dependency without a one-line justification"]:
                self.assertIn(line, text, line)
            self.assertNotIn("Components live next to", text)
            self.assertNotIn("abcd1234", text)
            self.assertNotIn("hunter2", text)
            self.assertIn("token_budget: 777", run("briefing", "hello", "st-03", ws=ws).stdout)
            missing = run("briefing", "hello", "st-09", ws=ws)
            self.assertEqual(missing.returncode, 1)
            self.assertIn("no sub-task st-09", missing.stderr)
