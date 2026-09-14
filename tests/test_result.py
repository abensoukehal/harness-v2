import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from helpers import BIN
from harness.ask import render

ASK = {
    "where": "The coupon field is on the checkout page and the discount shows in the total.",
    "stuck": "Two prices can apply to the same order. The spec does not say which one wins.",
    "tried": ["Applying the larger discount", "Applying the first one entered"],
    "question": "Which discount should win when two apply?",
    "options": [{"letter": "A", "text": "The larger one", "recommended": True},
                {"letter": "B", "text": "The first one entered", "recommended": False},
                {"letter": "C", "text": "Refuse the second coupon", "recommended": False}],
    "still_running": "the order history screen",
    "detail": "product/features/checkout-coupons",
}
BASE = {"report": "Coupon field added.\nWaiting on the tie rule.\nTwo decisions recorded.", "files": [], "decisions": [], "frictions": [], "attempts": 1}


def validate(payload):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "r.json"
        p.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        return subprocess.run([str(BIN / "validate"), str(p), "--schema", "result"], capture_output=True, text=True)


class WorkerResult(unittest.TestCase):
    def test_complete_results_validate(self):
        for extra in [dict(status="done", lines_added=12), dict(status="failed", last_error="assert 3 == 2"),
                      dict(status="blocked", reason="oracle"), dict(status="restart", stack="api"), dict(status="needs", ask=ASK)]:
            done = validate(dict(BASE, **extra))
            self.assertEqual(done.returncode, 0, "%s: %s" % (extra["status"], done.stderr))

    def test_one_observation_in_the_form_of_an_assumption(self):
        ok = validate(dict(BASE, status="done", lines_added=12, noted="orders carry a soft delete flag the plan does not mention"))
        self.assertEqual(ok.returncode, 0, ok.stderr)
        for line in ["the flag lives in app/models/order.py", "the filter calls `soft_deleted`", "two lines\nof it", "", "x" * 161]:
            bad = validate(dict(BASE, status="done", lines_added=12, noted=line))
            self.assertEqual(bad.returncode, 1, line)
            self.assertIn("/noted", bad.stderr, line)

    def test_prose_and_half_shapes_are_refused(self):
        cases = [
            ('"I finished the coupon field and everything passes."', "/"),
            ("{}", "/status"),
            (dict(status="done"), "/report"),
            (dict(BASE, status="done"), "/lines_added"),
            (dict(BASE, status="restart"), "/stack"),
            (dict(BASE, status="needs"), "/ask"),
            (dict(BASE, status="blocked", reason="tired"), "/reason"),
            (dict(BASE, status="failed", last_error="x", attempts=4), "/attempts"),
            (dict(BASE, status="done", lines_added=1, summary="extra prose"), "/summary"),
        ]
        for payload, path in cases:
            done = validate(payload)
            self.assertEqual(done.returncode, 1, path)
            self.assertIn(":%s:" % path, done.stderr, path)

    def test_ask_must_be_phone_readable(self):
        def ask(**changes):
            a = json.loads(json.dumps(ASK))
            a.update(changes)
            return dict(BASE, status="needs", ask=a)
        cases = [
            (ask(question="Should repos/backend/app.py check the id first?"), "/ask/question"),
            (ask(stuck="The handler in checkout.py throws."), "/ask/stuck"),
            (ask(options=[dict(ASK["options"][0], text="Edit views.py"), ASK["options"][1]]), "/ask/options/0/text"),
            (ask(options=[dict(ASK["options"][0]), dict(ASK["options"][1], recommended=True)]), "/ask/options"),
            (ask(options=[ASK["options"][0]]), "/ask/options"),
            (ask(options=[dict(ASK["options"][0], letter="B"), dict(ASK["options"][1], letter="A")]), "/ask/options"),
            (ask(tried=["one", "two", "three"]), "/ask/tried"),
        ]
        for payload, path in cases:
            done = validate(payload)
            self.assertEqual(done.returncode, 1, path)
            self.assertIn(":%s" % path, done.stderr, path)

    def test_render_reads_from_a_phone(self):
        text = render(ASK)
        lines = text.rstrip("\n").split("\n")
        self.assertEqual(lines[0], ASK["where"])
        self.assertIn("Tried: Applying the larger discount", text)
        self.assertIn("A. The larger one (recommended)", text)
        self.assertIn("B. The first one entered", text)
        self.assertNotIn("B. The first one entered (recommended)", text)
        self.assertEqual(lines[-2], "Still running: the order history screen")
        self.assertEqual(lines[-1], "Detail: product/features/checkout-coupons")
        self.assertLess(len(text), 700)
        self.assertLess(text.index("Which discount"), text.index("A. "))
