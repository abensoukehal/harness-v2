import re
import unittest

from helpers import ROOT
from harness.corpus import prompt_text, total

CAP = 40000
AGENTS = sorted((ROOT / "claude" / "agents").glob("*.md"))
SKILLS = sorted((ROOT / "claude" / "skills").glob("*/SKILL.md"))
WORKFLOWS = sorted((ROOT / "claude" / "workflows").glob("*.js"))
TECH = re.compile(r"\b(pytest|playwright|django|flask|fastapi|rails|react|next\.?js|vue|angular|svelte|node|npm|pnpm|yarn|"
                  r"python|pip|docker|kubernetes|postgres|mysql|sqlite|redis|swift|kotlin|flutter|typescript|javascript|java|"
                  r"golang|rust|jest|vitest|cypress|selenium|puppeteer|uvicorn|gunicorn|nginx|graphql|prisma|expo)\b", re.I)
JUSTIFICATION = re.compile(r"\b(because|so that|in order to|the reason|this is why|otherwise)\b", re.I)


def frontmatter(path):
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(line.split(":", 1) for line in m.group(1).splitlines()) if m else {}


class Corpus(unittest.TestCase):
    def test_total_under_cap(self):
        count = total(ROOT)
        print("\ninstruction corpus: %d characters (cap %d)" % (count, CAP))
        self.assertLess(count, CAP)

    def test_prompt_text_in_a_workflow_counts_as_prose(self):
        """A sentence an agent reads is corpus wherever it is written, and a script is a place it is written."""
        for p in WORKFLOWS:
            self.assertGreater(len(prompt_text(p.read_text())), 500, p.name)
        # The QA prompt's comparable branch: prose, in a script, reaching an agent.
        build = prompt_text((ROOT / "claude/workflows/harness-build.js").read_text())
        self.assertIn("capture no screen and report no visual failure", build)
        self.assertNotIn("agentType", build, "the code around the prose is not corpus")
        self.assertEqual(prompt_text("const x = 'object'\nconst y = `a ${b} c`\n"), "a  c",
                         "schema keywords fall under the length; an interpolation is not prose")

    def test_all_roles_present(self):
        self.assertEqual([p.stem for p in AGENTS], ["planner", "qa", "retro", "reviewer", "test-writer", "worker"])
        self.assertEqual([p.parent.name for p in SKILLS], ["commit-hygiene", "communicate", "criteria-runner", "reduce",
                                                           "retro", "visual-diff"])

    def test_agents_name_no_technology(self):
        for p in AGENTS:
            m = TECH.search(p.read_text())
            self.assertIsNone(m, "%s names %r" % (p.name, m and m.group(0)))

    def test_no_justification_in_agents_or_skills(self):
        for p in AGENTS + SKILLS:
            m = JUSTIFICATION.search(p.read_text())
            self.assertIsNone(m, "%s explains itself with %r" % (p, m and m.group(0)))

    def test_no_copied_preamble(self):
        bodies = [p.read_text().split("---", 2)[2] for p in AGENTS]
        for i, a in enumerate(bodies):
            for b in bodies[i + 1:]:
                shared = [line for line in a.splitlines() if len(line) > 40 and line in b.splitlines()]
                self.assertEqual(shared, [], "agents share the line %r" % (shared and shared[0]))

    def test_frontmatter(self):
        for p in AGENTS:
            fm = frontmatter(p)
            self.assertEqual(fm.get("name", "").strip(), p.stem, p.name)
            self.assertTrue(fm.get("description", "").strip(), p.name)
            self.assertTrue(fm.get("tools", "").strip(), p.name)
        for p in SKILLS:
            fm = frontmatter(p)
            self.assertEqual(fm.get("name", "").strip(), p.parent.name, p)
            self.assertTrue(fm.get("description", "").strip(), p)
