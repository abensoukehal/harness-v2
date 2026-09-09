import json
import tempfile
import unittest
from pathlib import Path

from helpers import env_workspace, run


class Frictions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ws = env_workspace(Path(self.tmp.name))
        self.ledger = self.ws / "product/frictions.md"

    def friction(self, cause, feature, *category):
        done = run("friction", cause, feature, *category, ws=self.ws)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_cause_outside_the_four_words_waits_for_a_second_run(self):
        first = self.friction("briefing-names-dependents-oddly", "hello")
        self.assertEqual((first["count"], first["eligible"]), (1, False))
        self.assertIn("waits for a second run", first["why"])
        self.assertIn("briefing-names-dependents-oddly | 1 | hello", self.ledger.read_text())
        # The same run hitting it again is the same evidence.
        again = self.friction("briefing-names-dependents-oddly", "hello")
        self.assertEqual((again["count"], again["eligible"], again["runs"]), (1, False, ["hello"]))
        second = self.friction("briefing-names-dependents-oddly", "other")
        self.assertEqual((second["count"], second["eligible"], second["runs"]), (2, True, ["hello", "other"]))
        self.assertIn("seen in 2 runs: hello, other", second["why"])
        self.assertIn("briefing-names-dependents-oddly | 2 | hello, other", self.ledger.read_text())

    def test_the_four_causes_move_on_the_first_occurrence(self):
        for cause, word in [("false-green-baseline-was-a-directory", "false green"), ("secret-shredded-every-path", "secret"),
                            ("delivery-pushed-an-empty-branch", "delivery"), ("net-check-guard-bypassed", "guard bypassed")]:
            out = self.friction(cause, "hello")
            self.assertTrue(out["eligible"], cause)
            self.assertIn(word, out["why"])
        # A word inside a longer one names nothing: this waits like anything else.
        self.assertFalse(self.friction("secrets-directory-listed", "hello")["eligible"])

    def test_a_declared_category_moves_the_engine_whatever_the_slug_says(self):
        # The slug names none of the four words, so on its spelling alone this would wait for a second run.
        out = self.friction("the-log-carried-a-token", "hello", "secret")
        self.assertEqual((out["count"], out["eligible"], out["category"]), (1, True, "secret"))
        self.assertIn("the cause is 'secret'", out["why"])
        bad = run("friction", "the-log-carried-a-token", "hello", "urgent", ws=self.ws)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("a category is one of false-green, secret, delivery, guard-bypassed", bad.stderr)

    def test_the_ledger_keeps_one_row_per_cause_and_a_header(self):
        self.friction("one-cause", "hello")
        self.friction("another-cause", "hello")
        self.friction("one-cause", "other")
        lines = self.ledger.read_text().splitlines()
        self.assertEqual(lines[0], "cause | count | runs")
        self.assertEqual(lines[1:], ["one-cause | 2 | hello, other", "another-cause | 1 | hello"])
        bad = run("friction", "Not A Slug", "hello", ws=self.ws)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("a cause is a lowercase slug", bad.stderr)


if __name__ == "__main__":
    unittest.main()
