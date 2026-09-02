import copy
import contextlib
import datetime
import io
import json
import pathlib
import tempfile
import unittest

import generate_pages as pages


TODAY = datetime.date(2026, 9, 2)


class GuideGeneratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = json.loads(pages.STATES_JSON.read_text(encoding="utf-8"))
        cls.states, cls.verified_on = pages.load_states(today=TODAY)

    def write_fixture(self, data: dict) -> pathlib.Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        directory = pathlib.Path(temporary_directory.name)
        path = directory / "states.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_internal_research_fields_never_enter_published_state(self):
        forbidden = {
            "warning",
            "correction",
            "model_impact",
            "roadready_note",
            "digital_note",
        }
        for state in self.states.values():
            self.assertTrue(forbidden.isdisjoint(state))

    def test_nested_conditional_target_is_whitelisted(self):
        conditional = self.states["MN"]["conditional_target"]
        self.assertEqual(conditional["total"], 40)
        self.assertNotIn("inverted", conditional)
        self.assertTrue(set(conditional) <= pages.CONDITIONAL_TARGET_FIELDS)

    def test_conditional_and_state_specific_rules_are_rendered(self):
        _, minnesota, _ = pages.state_page("MN", self.states["MN"], self.verified_on)
        self.assertIn("Minnesota supervised driving: 40 or 50 hours", minnesota)
        self.assertIn("If the parent completes the 90-minute awareness course", minnesota)

        _, nevada, _ = pages.state_page("NV", self.states["NV"], self.verified_on)
        self.assertIn("Nevada supervised driving: 50 or 100 hours", nevada)
        self.assertIn("Night means</th><td>in darkness", nevada)

        _, florida, _ = pages.state_page("FL", self.states["FL"], self.verified_on)
        self.assertIn("daylight only for the first 3 months", florida)

        _, north_carolina, _ = pages.state_page("NC", self.states["NC"], self.verified_on)
        self.assertIn("licensed 5+ years", north_carolina)
        self.assertIn("digital or printed", north_carolina)

    def test_comparison_does_not_claim_roadready_specific_import(self):
        _, page, _ = pages.comparison_page(self.verified_on)
        self.assertIn("not verified any specific app", page)
        self.assertIn("won't promise one-click migration", page)
        self.assertNotIn("$4.99", page)

    def test_waitlist_mailto_is_url_encoded(self):
        block = pages.cta_block(None)
        self.assertIn("mailto:support@acsimsek.com?", block)
        self.assertIn("%5Benter+your+state%5D", block)
        self.assertNotIn("My state: [enter your state]", block)

    def test_unverified_pilot_state_blocks_build(self):
        data = copy.deepcopy(self.raw)
        next(state for state in data["states"] if state["code"] == "CA")["status"] = "draft"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pages.load_states(self.write_fixture(data), today=TODAY)

    def test_non_https_source_blocks_build(self):
        data = copy.deepcopy(self.raw)
        next(state for state in data["states"] if state["code"] == "CA")["source"] = (
            "http://example.com/rules"
        )
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pages.load_states(self.write_fixture(data), today=TODAY)

    def test_stale_or_future_verification_date_blocks_build(self):
        stale = copy.deepcopy(self.raw)
        stale["_meta"]["verified_on"] = "2026-05-01"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pages.load_states(self.write_fixture(stale), today=TODAY)

        future = copy.deepcopy(self.raw)
        future["_meta"]["verified_on"] = "2026-09-03"
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pages.load_states(self.write_fixture(future), today=TODAY)


if __name__ == "__main__":
    unittest.main()
