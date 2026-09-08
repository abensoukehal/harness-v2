import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (puts lib on sys.path)
from harness.secrets import Scrubber, load_env_file


class EnvFile(unittest.TestCase):
    def test_parses_dotenv_shapes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.env"
            p.write_text('# comment\n\nA=1\nexport B="two words"\nC=\'single\'\nD = spaced \nNOEQUALS\nE=a=b\n')
            self.assertEqual(load_env_file(p), {"A": "1", "B": "two words", "C": "single", "D": "spaced", "E": "a=b"})


class Scrub(unittest.TestCase):
    def test_replaces_every_occurrence_longest_first(self):
        s = Scrubber({"SHORT": "abcd", "LONG": "abcdefgh"})
        self.assertEqual(s.scrub("x abcdefgh y abcd z abcdefgh"), "x [REDACTED LONG] y [REDACTED SHORT] z [REDACTED LONG]")

    def test_ignores_tiny_values(self):
        self.assertEqual(Scrubber({"PORT": "80", "FLAG": "1"}).scrub("port 80 flag 1"), "port 80 flag 1")

    def test_no_secrets_is_identity(self):
        self.assertEqual(Scrubber({}).scrub("plain text"), "plain text")
