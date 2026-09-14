"""The measurement inventory (6.2.1) against the code, not against itself.

What this proves is narrow and the narrowness is deliberate. It matches a field by its name, so it catches a number
nothing in the engine loads, and it does not catch a number loaded under the wrong owner. A coverage check that errs
toward passing has to say which way it errs, so this docstring says it here and 6.2.1 says it in the spec.
"""
import ast
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = re.compile(r"^\| (?!number |---)(.+?) \| (.+?) \| (.+?) \|$", re.M)
TICKED = re.compile(r"`([a-z_][a-z0-9_]*)`")


def section(name):
    text = (ROOT / "SPEC.md").read_text()
    start = text.index("### %s" % name)
    return text[start:text.index("\n### ", start + 1)]


def numeric_fields():
    """Every number state.json records, by name, from the schema itself."""
    schema = json.loads((ROOT / "schemas/state.schema.json").read_text())
    defs = schema["$defs"]
    found, seen = set(), set()

    def resolve(node):
        # A ref into another document — the worker result's ask — stays where it is: that schema is not state.
        ref = node.get("$ref", "")
        return defs.get(ref.split("/")[-1], node) if ref.startswith("#/") else node

    def walk(node):
        node = resolve(node)
        if id(node) in seen:
            return
        seen.add(id(node))
        for name, sub in node.get("properties", {}).items():
            target = resolve(sub)
            if target.get("type") in ("integer", "number"):
                found.add(name)
            walk(sub)
        for key in ("items", "additionalProperties"):
            if isinstance(node.get(key), dict):
                walk(node[key])

    walk(schema)
    return found


class Loads(ast.NodeVisitor):
    """A name the code reads: a subscript in a load context, or a `.get`. A store and a `.setdefault` are writes."""

    def __init__(self):
        self.names = set()

    def visit_Subscript(self, node):
        key = node.slice.value if isinstance(node.slice, ast.Constant) else None
        if isinstance(key, str) and not isinstance(node.ctx, ast.Store):
            self.names.add(key)
        self.generic_visit(node)

    def visit_Call(self, node):
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "get"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            self.names.add(node.args[0].value)
        self.generic_visit(node)


def loaded():
    names = set()
    for path in sorted(list((ROOT / "lib/harness").glob("*.py")) + [f for f in (ROOT / "bin").iterdir() if f.is_file()]):
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        reader = Loads()
        reader.visit(tree)
        names |= reader.names
    return names


def unread(fields, read, debt):
    """The rule itself, over data: a recorded number the engine never loads and nobody wrote down."""
    return sorted(n for n in fields if n not in read and n not in debt)


class Inventory(unittest.TestCase):
    def setUp(self):
        self.rows = TABLE.findall(section("6.2.1"))
        self.assertGreater(len(self.rows), 5, "6.2.1 carries the table")
        self.named = {n for row in self.rows for n in TICKED.findall(row[0])}
        self.fields = numeric_fields()

    def test_every_number_the_schema_records_is_in_the_table(self):
        missing = sorted(self.fields - self.named)
        self.assertEqual(missing, [], "recorded and unaccounted: add a row to 6.2.1 naming the reader")

    def test_every_field_the_table_names_exists(self):
        schema = (ROOT / "schemas/state.schema.json").read_text()
        for name in sorted(self.named):
            self.assertIn('"%s"' % name, schema, "6.2.1 names %s and the schema has no such field" % name)

    def test_no_row_ships_without_a_reader(self):
        for number, _, readers in self.rows:
            self.assertTrue(readers.strip(), number)
            if readers.strip().startswith("nothing"):
                # A number with no reader stands only as written-down debt. Silence is what the rule refuses.
                debt = (ROOT / "OPEN_QUESTIONS.md").read_text()
                for name in TICKED.findall(number) or [number]:
                    self.assertIn(name, debt, "%s has no reader and no entry in OPEN_QUESTIONS.md" % name)

    def test_every_recorded_number_is_loaded_or_written_down_as_debt(self):
        """The rule with teeth: a number the engine never loads is deleted, or it is carried as a named debt."""
        self.assertEqual(unread(self.fields, loaded(), (ROOT / "OPEN_QUESTIONS.md").read_text()), [],
                         "recorded on every run and loaded by nothing under lib/ or bin/: give it a reader, "
                         "delete it, or carry it in OPEN_QUESTIONS.md")

    def test_the_rule_refuses_a_number_nothing_reads(self):
        """Driven with the input that trips it: a guard no input reaches passes its own test and protects nothing."""
        debt = (ROOT / "OPEN_QUESTIONS.md").read_text()
        self.assertEqual(unread({"tokens_hoarded"}, loaded(), debt), ["tokens_hoarded"])
        self.assertEqual(unread({"divergence_pct"}, loaded(), debt), [], "a named debt stands")
        self.assertEqual(unread({"attempts"}, loaded(), debt), [], "a loaded number stands")
