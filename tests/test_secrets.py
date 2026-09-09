import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts lib on sys.path)
from harness.secrets import Scrubber, load_env_file, too_short


class EnvFile(unittest.TestCase):
    def test_parses_dotenv_shapes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.env"
            p.write_text('# comment\n\nA=1\nexport B="two words"\nC=\'single\'\nD = spaced \nNOEQUALS\nE=a=b\n')
            self.assertEqual(load_env_file(p), {"A": "1", "B": "two words", "C": "single", "D": "spaced", "E": "a=b"})


class Scrub(unittest.TestCase):
    def test_replaces_every_occurrence_longest_first(self):
        s = Scrubber({"SHORT": "abcd1234", "LONG": "abcd1234efgh"})
        self.assertEqual(s.scrub("x abcd1234efgh y abcd1234 z abcd1234efgh"),
                         "x [REDACTED LONG] y [REDACTED SHORT] z [REDACTED LONG]")

    def test_the_floor_is_refused_at_load_and_an_empty_value_substitutes_nothing(self):
        self.assertEqual(too_short({"PORT": "80", "ENV": "dryrun3", "KEY": "abcd1234", "EMPTY": ""}), ["ENV", "PORT"])
        # An empty value matches at every token boundary; it is dropped, and a real one beside it still goes.
        s = Scrubber({"EMPTY": "", "KEY": "abcd1234"})
        self.assertEqual(s.scrub("port 80 key abcd1234"), "port 80 key [REDACTED KEY]")

    def test_a_value_inside_a_longer_token_leaves_the_path_alone(self):
        s = Scrubber({"KEY": "dryrun3x"})
        # The secret is a path segment: the segment goes, the path around it stays readable.
        self.assertEqual(s.scrub("/tmp/e2e/dryrun3x/harness/bin/up failed"), "/tmp/e2e/[REDACTED KEY]/harness/bin/up failed")
        # And it is part of a longer word here, so it is not that word: nothing is substituted.
        for line in ["/tmp/e2e/dryrun3xyz/harness refused", "the dryrun3x_key variable", "adryrun3x"]:
            self.assertEqual(s.scrub(line), line)

    def test_no_secrets_is_identity(self):
        self.assertEqual(Scrubber({}).scrub("plain text"), "plain text")
