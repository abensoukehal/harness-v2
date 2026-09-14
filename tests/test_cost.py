import json
import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run
from harness.config import load_state, save_state
from test_next import st


def transcript(folder, agent_id, agent_type, first_text, turns, start_minute, model="claude-opus-5", effort="low", tools=()):
    lines = [{"type": "user", "message": {"role": "user", "content": first_text}, "timestamp": "2026-01-01T10:%02d:00.000Z" % start_minute}]
    for i, (tin, cache_new, cache_read, tout) in enumerate(turns):
        call = tools[i] if i < len(tools) else None
        lines.append({"type": "assistant", "timestamp": "2026-01-01T10:%02d:%02d.000Z" % (start_minute, 10 * (i + 1)), "effort": effort,
                      "message": {"role": "assistant", "model": model, "content": [dict(call, type="tool_use")] if call else [{"type": "text", "text": "done"}],
                                  "usage": {"input_tokens": tin, "cache_creation_input_tokens": cache_new,
                                                                 "cache_read_input_tokens": cache_read, "output_tokens": tout}}})
    (folder / ("agent-%s.jsonl" % agent_id)).write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    (folder / ("agent-%s.meta.json" % agent_id)).write_text(json.dumps({"agentType": agent_type, "spawnDepth": 1}))


class Cost(unittest.TestCase):
    def test_input_tokens_per_agent_from_transcripts(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d))
            state = load_state(ws, "hello")
            state["subtasks"] = [st("st-01", "api", "svc", status="done", attempts=1, commit="a" * 40,
                                    cost={"tokens_in": 0, "tokens_out": 7, "duration_s": 0, "lines_added": 12})]
            save_state(ws, "hello", state)
            wf = Path(d) / "wf_1"
            wf.mkdir()
            transcript(wf, "aaa1", "workflow-subagent", "Workspace root: %s. Run `%s/harness/bin/plan hello`." % (ws, ws), [(2, 51000, 0, 21), (32, 2000, 51000, 26)], 0)
            transcript(wf, "aaa2", "planner", "Workspace root: %s. Feature hello. Run the Ingestion part" % ws, [(10, 100000, 0, 900), (5, 0, 100000, 1100)], 1)
            transcript(wf, "aaa3", "worker", "# Mission st-01 · Orders export\nfeature: hello   branch: feature/hello\nworkspace: %s" % ws, [(1, 0, 120000, 3000)], 2)
            transcript(wf, "aaa4", "workflow-subagent", "Workspace root: %s. Run `%s/harness/bin/briefing hello st-01`." % (ws, ws), [(1, 0, 100000, 40)], 3)
            transcript(wf, "bbb1", "worker", "# Mission st-01 · Something else\nfeature: hello-world   branch: feature/hello-world\nworkspace: %s" % ws, [(1, 0, 999999, 1)], 4)
            transcript(wf, "ccc1", "workflow-subagent", 'Run `printf %s "$HARNESS_WORKSPACE"`', [(1, 0, 50000, 5)], 5)
            transcript(wf, "ddd1", "test-writer", "Workspace root: %s-other. Feature hello. Follow your Method" % ws, [(1, 0, 999999, 1)], 6)
            done = run("cost", "hello", "--transcripts", wf, ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            state = load_state(ws, "hello")
            agents = state["cost_by_agent"]
            self.assertEqual(sorted(agents), ["aaa1", "aaa2", "aaa3", "aaa4"], "only agents whose first message names the feature and this workspace")
            self.assertEqual(agents["aaa1"], {"role": "io", "run": "wf_1", "model": "claude-opus-5", "effort": "low",
                                              "tokens_in": 104034, "tokens_distinct": 53034, "tokens_out": 47, "turns": 2,
                                              "turns_by_kind": {"locate": 0, "read": 0, "write": 0, "other": 2}, "duration_s": 20})
            self.assertEqual(agents["aaa2"]["role"], "planner")
            self.assertEqual(agents["aaa2"]["tokens_in"], 200015)
            # aaa1 and aaa2 each re-read on their second turn what their first turn established: the two numbers part.
            self.assertEqual(agents["aaa2"]["tokens_distinct"], 100015)
            for aid in ["aaa1", "aaa2"]:
                self.assertLess(agents[aid]["tokens_distinct"], agents[aid]["tokens_in"], aid)
            # A one-turn agent has nothing to re-read, so the two agree and the pair stays readable.
            self.assertEqual(agents["aaa4"]["tokens_distinct"], agents["aaa4"]["tokens_in"])
            self.assertEqual((agents["aaa3"]["subtask"], agents["aaa4"]["subtask"]), ("st-01", "st-01"))
            cost = state["subtasks"][0]["cost"]
            self.assertEqual((cost["tokens_in"], cost["tokens_out"], cost["lines_added"]), (220002, 3040, 12))
            self.assertEqual(cost["duration_s"], 20, "from the agents' own spans when the loop recorded none")
            self.assertEqual(state["wall_time_s"], 190, "first agent start to last agent end inside the run")
            self.assertIn("planner: 1 agents, 200k in (100k distinct), 2k out, 2 turns, 0% locate (claude-opus-5/low)", done.stdout,
                          "the pair that spent the tokens, read from the transcript (6.3)")
            self.assertIn("total: 4 agents over 1 run, 524k in (373k distinct), 5k out, 6 turns, 0% locate, 190 s wall", done.stdout)
            self.assertNotIn("timestamp", json.dumps(state))
            again = run("cost", "hello", "--transcripts", wf, ws=ws)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(len(load_state(ws, "hello")["cost_by_agent"]), 4, "a second pass overwrites, never doubles")
            report = run("report", "hello", ws=ws).stdout
            self.assertIn("529k tokens (378k distinct), 190 s wall time, 1 sub-tasks, 1 attempts, 0 blocked.", report)
            self.assertIn("By role: io: 2 agents", report)
            self.assertIn("By role: io: 2 agents, 204k in (153k distinct), 87 out, 3 turns, 0% locate (claude-opus-5/low); "
                          "planner: 1 agents, 200k in (100k distinct), 2k out, 2 turns, 0% locate (claude-opus-5/low); "
                          "worker: 1 agents, 120k in (120k distinct), 3k out, 1 turns, 0% locate (claude-opus-5/low).", report)
            self.assertIn("hello | 529", (ws / "product/cost-log.md").read_text())
            self.assertRegex((ws / "product/cost-log.md").read_text(), r"hello \| 529\d+ \| 378\d+ \| 190 \| 1 \| 0")
            missing = run("cost", "hello", "--transcripts", Path(d) / "nowhere", ws=ws)
            self.assertEqual(missing.returncode, 0, "a missing directory holds no agents")

            # A second run of the same feature, hours later in the same session folder: its own span, not the gap between them.
            later = Path(d) / "wf_2"
            later.mkdir()
            transcript(later, "eee1", "worker", "# Mission st-01 · Orders export\nfeature: hello\nworkspace: %s" % ws, [(1, 0, 10000, 100)], 40)
            transcript(later, "eee2", "reviewer", "Workspace root: %s. Feature hello. Review st-01" % ws, [(1, 0, 20000, 200)], 41)
            done = run("cost", "hello", "--transcripts", wf, "--transcripts", later, ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            state = load_state(ws, "hello")
            self.assertEqual(state["wall_time_s"], 190 + 70, "each run's own span, never the idle time between them")
            self.assertEqual({a["run"] for a in state["cost_by_agent"].values()}, {"wf_1", "wf_2"})
            # State written by an earlier engine carries no run; it stays readable and counts once.
            state["cost_by_agent"]["old1"] = {"role": "worker", "tokens_in": 5, "tokens_out": 1, "duration_s": 2}
            save_state(ws, "hello", state)
            self.assertEqual(run("cost", "hello", "--transcripts", wf, ws=ws).returncode, 0)
            self.assertIn("total: 6 agents over 2 runs,", done.stdout)

    def test_turns_are_classified_by_what_they_did(self):
        with tempfile.TemporaryDirectory() as d:
            ws = env_workspace(Path(d))
            wf = Path(d) / "wf_1"
            wf.mkdir()
            transcript(wf, "aaa1", "worker", "# Mission st-01\nfeature: hello\nworkspace: %s" % ws,
                       [(1, 0, 1000, 10)] * 4, 0,
                       tools=[{"name": "Bash", "input": {"command": "grep -rn parse_order lib/"}},
                              {"name": "Read", "input": {"file_path": "lib/orders.py"}},
                              {"name": "Bash", "input": {"command": "cat > lib/orders.py <<EOF"}},
                              None])
            done = run("cost", "hello", "--transcripts", wf, ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            agent = load_state(ws, "hello")["cost_by_agent"]["aaa1"]
            self.assertEqual(agent["turns"], 4)
            self.assertEqual(agent["turns_by_kind"], {"locate": 1, "read": 1, "write": 1, "other": 1},
                             "the grep turn and the read turn classify differently")
            self.assertIn("worker: 1 agents, 4k in (1k distinct), 40 out, 4 turns, 25% locate", done.stdout)
            self.assertIn("4 turns, 25% locate, ", done.stdout)
