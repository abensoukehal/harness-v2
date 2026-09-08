import json
import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run
from harness.config import load_state, save_state
from test_next import st


def transcript(folder, agent_id, agent_type, first_text, turns, start_minute):
    lines = [{"type": "user", "message": {"role": "user", "content": first_text}, "timestamp": "2026-01-01T10:%02d:00.000Z" % start_minute}]
    for i, (tin, cache_new, cache_read, tout) in enumerate(turns):
        lines.append({"type": "assistant", "timestamp": "2026-01-01T10:%02d:%02d.000Z" % (start_minute, 10 * (i + 1)),
                      "message": {"role": "assistant", "usage": {"input_tokens": tin, "cache_creation_input_tokens": cache_new,
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
            transcript(wf, "aaa1", "workflow-subagent", "Workspace root: /x. Run `/x/harness/bin/plan hello`.", [(2, 51000, 0, 21), (32, 2000, 51000, 26)], 0)
            transcript(wf, "aaa2", "planner", "Workspace root: /x. Feature hello. Run the Ingestion part", [(10, 100000, 0, 900), (5, 0, 100000, 1100)], 1)
            transcript(wf, "aaa3", "worker", "# Mission st-01 · Orders export\nfeature: hello   branch: feature/hello", [(1, 0, 120000, 3000)], 2)
            transcript(wf, "aaa4", "workflow-subagent", "Workspace root: /x. Run `/x/harness/bin/briefing hello st-01`.", [(1, 0, 100000, 40)], 3)
            transcript(wf, "bbb1", "worker", "# Mission st-01 · Something else\nfeature: hello-world   branch: feature/hello-world", [(1, 0, 999999, 1)], 4)
            transcript(wf, "ccc1", "workflow-subagent", 'Run `printf %s "$HARNESS_WORKSPACE"`', [(1, 0, 50000, 5)], 5)
            done = run("cost", "hello", "--transcripts", wf, ws=ws)
            self.assertEqual(done.returncode, 0, done.stderr)
            state = load_state(ws, "hello")
            agents = state["cost_by_agent"]
            self.assertEqual(sorted(agents), ["aaa1", "aaa2", "aaa3", "aaa4"], "only agents whose first message names the feature")
            self.assertEqual(agents["aaa1"], {"role": "io", "tokens_in": 104034, "tokens_out": 47, "turns": 2, "duration_s": 20})
            self.assertEqual(agents["aaa2"]["role"], "planner")
            self.assertEqual(agents["aaa2"]["tokens_in"], 200015)
            self.assertEqual((agents["aaa3"]["subtask"], agents["aaa4"]["subtask"]), ("st-01", "st-01"))
            cost = state["subtasks"][0]["cost"]
            self.assertEqual((cost["tokens_in"], cost["tokens_out"], cost["lines_added"]), (220002, 3040, 12))
            self.assertEqual(cost["duration_s"], 20, "from the agents' own spans when the loop recorded none")
            self.assertEqual(state["wall_time_s"], 190, "first agent start to last agent end")
            self.assertIn("planner: 1 agents, 200k in, 2k out", done.stdout)
            self.assertIn("total: 4 agents, 524k in, 5k out, 190 s wall", done.stdout)
            self.assertNotIn("timestamp", json.dumps(state))
            again = run("cost", "hello", "--transcripts", wf, ws=ws)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertEqual(len(load_state(ws, "hello")["cost_by_agent"]), 4, "a second pass overwrites, never doubles")
            report = run("report", "hello", ws=ws).stdout
            self.assertIn("529k tokens, 190 s wall time, 1 sub-tasks, 1 attempts, 0 blocked.", report)
            self.assertIn("By role: io: 2 agents, 204k in, 87 out; planner: 1 agents, 200k in, 2k out; worker: 1 agents, 120k in, 3k out.", report)
            self.assertIn("hello | 529", (ws / "product/cost-log.md").read_text())
            missing = run("cost", "hello", "--transcripts", Path(d) / "nowhere", ws=ws)
            self.assertEqual(missing.returncode, 0, "a missing directory holds no agents")
