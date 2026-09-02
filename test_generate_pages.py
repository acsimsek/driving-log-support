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

    def test_all_fifty_states_and_dc_are_publishable(self):
        self.assertEqual(set(self.states), pages.EXPECTED_JURISDICTIONS)
        self.assertEqual(len(self.states), 51)
        slugs = [pages.slug_for(code, state["name"]) for code, state in self.states.items()]
        self.assertEqual(len(slugs), len(set(slugs)))

    def test_every_state_page_has_unique_metadata_source_and_campaign(self):
        titles = set()
        descriptions = set()
        for code, state in self.states.items():
            _, page, title = pages.state_page(code, state, self.verified_on)
            self.assertNotIn("None hours", page)
            self.assertIn(state["source"].replace("&", "&amp;"), page)
            self.assertIn(f"ct=guide-{code.lower()}", page)
            title_tag = page.split("<title>", 1)[1].split("</title>", 1)[0]
            description = page.split('<meta name="description" content="', 1)[1].split('">', 1)[0]
            titles.add(title_tag)
            descriptions.add(description)
            self.assertEqual(title_tag, title)
            self.assertLessEqual(len(title_tag), 60)
            self.assertLessEqual(len(description), 165)
        self.assertEqual(len(titles), 51)
        self.assertEqual(len(descriptions), 51)

    def test_nested_conditional_target_is_whitelisted(self):
        conditional = self.states["MN"]["conditional_target"]
        self.assertEqual(conditional["total"], 40)
        self.assertNotIn("inverted", conditional)
        self.assertTrue(set(conditional) <= pages.CONDITIONAL_TARGET_FIELDS)

    def test_conditional_and_state_specific_rules_are_rendered(self):
        _, minnesota, _ = pages.state_page("MN", self.states["MN"], self.verified_on)
        self.assertIn("Minnesota supervised driving: 40 or 50 hours", minnesota)
        self.assertIn("If the parent completes the 90-minute awareness course", minnesota)
        self.assertIn("ct=guide-mn", minnesota)

        _, nevada, _ = pages.state_page("NV", self.states["NV"], self.verified_on)
        self.assertIn("Nevada supervised driving: 50 or 100 hours", nevada)
        self.assertIn("Night means</th><td>in darkness", nevada)

        _, florida, _ = pages.state_page("FL", self.states["FL"], self.verified_on)
        self.assertIn("daylight only for the first 3 months", florida)

        _, north_carolina, _ = pages.state_page("NC", self.states["NC"], self.verified_on)
        self.assertIn("licensed 5+ years", north_carolina)
        self.assertIn("digital or printed", north_carolina)

        _, arkansas, _ = pages.state_page("AR", self.states["AR"], self.verified_on)
        self.assertIn("No numeric minimum is stated", arkansas)
        self.assertIn("180 days", arkansas)

        _, hawaii, _ = pages.state_page("HI", self.states["HI"], self.verified_on)
        self.assertIn("Hawaii supervised driving: 50 hours", hawaii)
        self.assertIn("10 hours", hawaii)
        self.assertIn("age 21+", hawaii)
        self.assertIn("notarized", hawaii)
        self.assertIn("Acknowledgement-of-Practice-Driving-Log.pdf", hawaii)

        _, iowa, _ = pages.state_page("IA", self.states["IA"], self.verified_on)
        self.assertIn("20 hours before the intermediate license", iowa)
        self.assertIn("10 additional hours", iowa)

        _, nebraska, _ = pages.state_page("NE", self.states["NE"], self.verified_on)
        self.assertIn("Alternative path", nebraska)
        self.assertIn("alternative to the 50-hour parent certification", nebraska)

        _, north_dakota, _ = pages.state_page("ND", self.states["ND"], self.verified_on)
        self.assertIn("rural, city, gravel dirt aggregate road, night, winter", north_dakota)

    def test_comparison_does_not_claim_roadready_specific_import(self):
        _, page, _ = pages.comparison_page(self.verified_on)
        self.assertIn("not verified any specific app", page)
        self.assertIn("won't promise one-click migration", page)
        self.assertNotIn("$4.99", page)

    def test_waitlist_mailto_is_url_encoded(self):
        block = pages.cta_block(None, "compare-roadready")
        self.assertIn("mailto:support@acsimsek.com?", block)
        self.assertIn("%5Benter+your+state%5D", block)
        self.assertNotIn("My state: [enter your state]", block)

    def test_app_store_campaign_link_is_attributed(self):
        block = pages.cta_block("California", "guide-ca")
        self.assertIn("pt=129248493&amp;ct=guide-ca&amp;mt=8", block)

    def test_cta_describes_icloud_as_optional(self):
        block = pages.cta_block("California", "guide-ca")
        self.assertIn("when enabled", block)
        self.assertNotIn("stored on your iPhone and in your own private iCloud", block)

    def test_homepage_has_main_landmark_and_avoids_absolute_claims(self):
        homepage = (pathlib.Path(__file__).parent / "index.html").read_text(encoding="utf-8")
        self.assertEqual(homepage.count("<main>"), 1)
        self.assertEqual(homepage.count("</main>"), 1)
        self.assertNotIn("see exactly what counts", homepage)
        self.assertNotIn("the total that will hold up", homepage)
        self.assertNotIn("If the other app can export a CSV file", homepage)
        self.assertIn("supported rows from a CSV file", homepage)

    def test_unverified_state_blocks_build(self):
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
