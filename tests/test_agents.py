import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from helpers import env_config, env_workspace, run
from harness.agents import ROLES, options

def block(body):
    """env_config splices extra in before its own dedent, so it arrives at the template's indentation."""
    return textwrap.indent(textwrap.dedent(body).strip("\n"), " " * 8).lstrip()


BLOCK = block("""
    agents:
      worker: {model: claude-opus-5, effort: high}
      io: {model: claude-haiku-4-5-20251001, effort: low}
      planner: {model: inherit, effort: inherit}
""")


class Agents(unittest.TestCase):
    def test_a_workspace_with_no_block_keeps_the_documented_defaults(self):
        opts = options({})
        self.assertEqual(sorted(opts), sorted(ROLES))
        self.assertEqual(opts["io"], {"effort": "low"}, "the mechanical steps run at low effort (6.3)")
        self.assertEqual(opts["worker"], {}, "every other role inherits the session")

    def test_inherit_is_the_session_setting_and_reaches_no_spawn(self):
        opts = options({"agents": {"worker": {"model": "claude-opus-5", "effort": "high"},
                                   "planner": {"model": "inherit", "effort": "inherit"},
                                   "io": {"model": "inherit", "effort": "medium"}}})
        self.assertEqual(opts["worker"], {"model": "claude-opus-5", "effort": "high"})
        self.assertEqual(opts["planner"], {}, "inherit is a value, and it passes nothing")
        self.assertEqual(opts["io"], {"effort": "medium"}, "a declared effort replaces the default")

    def test_the_tool_reads_the_workspace_it_is_given_not_the_one_it_stands_in(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d), config=env_config(extra=BLOCK))
            done = run("agents", ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(json.loads(done.stdout)["worker"], {"model": "claude-opus-5", "effort": "high"})
            self.assertEqual(json.loads(done.stdout)["planner"], {})

    def test_the_config_refuses_a_role_it_does_not_spawn_and_an_effort_that_is_not_one(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d))
            path = ws / "product" / "client.config.yaml"
            for bad, why in [("agents:\n  scribe: {model: inherit}", "scribe"),
                             ("agents:\n  worker: {effort: enormous}", "enormous"),
                             ("agents:\n  worker: {temperature: 0.4}", "temperature")]:
                bad = block(bad)
                path.write_text(env_config(extra=bad))
                done = run("agents", ws=ws)
                self.assertNotEqual(done.returncode, 0, "%s was accepted" % why)
            path.write_text(env_config(extra=BLOCK))
            self.assertEqual(run("agents", ws=ws).returncode, 0)

    def test_the_plan_hands_the_pairs_to_the_build(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d), config=env_config(extra=BLOCK))
            plan = ws / "product" / "features" / "hello" / "plan.md"
            plan.write_text(textwrap.dedent("""
                # hello
                kind: service

                ## st-01 · Orders export
                stack: api
                files: repos/svc/app.py
                depends_on: none
                line_budget: 40
                criteria:
                - lint
            """).strip() + "\n")
            done = run("plan", "hello", ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            agents = json.loads(done.stdout)["config"]["agents"]
            self.assertEqual(agents["worker"], {"model": "claude-opus-5", "effort": "high"})
            self.assertEqual(agents["io"], {"model": "claude-haiku-4-5-20251001", "effort": "low"})
