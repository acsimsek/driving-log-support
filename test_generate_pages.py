import copy
import contextlib
import datetime
import io
import json
import pathlib
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import urljoin, urldefrag

import generate_pages as pages


TODAY = datetime.date(2026, 9, 21)


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

    def test_every_published_page_is_reachable_from_home(self):
        class Links(HTMLParser):
            def __init__(self):
                super().__init__()
                self.hrefs = []

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "a" and attrs.get("href"):
                    self.hrefs.append(attrs["href"])

        documents = {}
        for filename in ("index.html", "support.html", "privacy.html"):
            path = "/" if filename == "index.html" else "/" + filename
            documents[pages.BASE_URL + path] = (pages.REPO / filename).read_text()
        entries = []
        for code, state in self.states.items():
            slug, markup, title = pages.state_page(code, state, self.verified_on, self.states)
            documents[f"{pages.BASE_URL}/guides/{slug}.html"] = markup
            entries.append((slug, state["name"], pages.guide_summary(state)))
        slug, markup, title = pages.comparison_page(self.verified_on)
        documents[f"{pages.BASE_URL}/guides/{slug}.html"] = markup
        entries.append((slug, title, ""))
        for slug, markup, _ in pages.content_pages(self.states, self.verified_on):
            documents[f"{pages.BASE_URL}/guides/{slug}.html"] = markup
        documents[f"{pages.BASE_URL}/guides/"] = pages.index_page(entries, self.verified_on)

        pending = [pages.BASE_URL + "/"]
        visited = set()
        while pending:
            url = pending.pop()
            if url in visited or url not in documents:
                continue
            visited.add(url)
            parser = Links()
            parser.feed(documents[url])
            pending.extend(urldefrag(urljoin(url, href))[0] for href in parser.hrefs)
        self.assertEqual(set(documents) - visited, set(), "Published pages need a crawlable path from home")

    def test_audit_daytime_stage_and_age_rules_are_published_consistently(self):
        _, texas, _ = pages.texas_deep_page(self.states["TX"], self.verified_on)
        self.assertIn("20 hours", texas)
        self.assertIn("10 or 15 at night", pages.direct_answer(self.states["MT"]))
        self.assertNotIn("30 separate days", texas)
        self.assertNotIn("30-day minimum.</li>", texas)
        for code, expected in [("HI", "40 hours; extra night"),
                               ("MT", "6 calendar months plus 1 day"),
                               ("MD", "45 days with the permit"),
                               ("NJ", "Turning 21 does not remove"),
                               ("VA", "2027-01-01"),
                               ("NC", "No separate hour quota"),
                               ("DC", "6 calendar months from the intermediate")]:
            _, page, _ = pages.state_page(code, self.states[code], self.verified_on)
            self.assertIn(expected, page, code)
        _, idaho, _ = pages.state_page("ID", self.states["ID"], self.verified_on)
        self.assertIn("Driver training completed / supervised practice started", idaho)
        self.assertNotIn("from the date the permit was issued", idaho)

    def test_new_nested_rule_fields_keep_research_private(self):
        data = copy.deepcopy(self.raw)
        state = next(state for state in data["states"] if state["code"] == "MD")
        state["applicant_paths"][0]["internal_research"] = "PRIVATE PATH NOTE"
        state = next(state for state in data["states"] if state["code"] == "NC")
        state["stage_targets"]["intermediate"]["internal_research"] = "PRIVATE STAGE NOTE"
        states, _ = pages.load_states(self.write_fixture(data), today=TODAY)
        self.assertNotIn("PRIVATE", json.dumps(states))

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
        self.assertIn("6 calendar months", arkansas)

        _, hawaii, _ = pages.state_page("HI", self.states["HI"], self.verified_on)
        self.assertIn("Hawaii supervised driving: 50 hours", hawaii)
        self.assertIn("10 hours", hawaii)
        self.assertIn("age 21+", hawaii)
        self.assertIn("notarized", hawaii)
        self.assertIn("https://hidot.hawaii.gov/highways/files/2013/01/HAR19-139.pdf", hawaii)
        self.assertIn("40 daytime hours", hawaii)
        self.assertIn("HRS_0286-0110.htm", hawaii)

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

    def test_homepage_product_tour_uses_real_local_app_captures(self):
        repo = pathlib.Path(__file__).parent
        homepage = (repo / "index.html").read_text(encoding="utf-8")
        expected_assets = {
            "dashboard.png",
            "progress.png",
            "add-drive.png",
            "pro.png",
        }
        for asset in expected_assets:
            self.assertIn(f'/assets/{asset}', homepage)
            self.assertTrue((repo / "assets" / asset).is_file())
            webp_asset = pathlib.Path(asset).with_suffix(".webp")
            self.assertIn(f'/assets/{webp_asset}', homepage)
            self.assertTrue((repo / "assets" / webp_asset).is_file())
        self.assertIn('aria-labelledby="inside-app"', homepage)
        self.assertEqual(homepage.count('class="screen-card'), 3)


    def test_content_pages_keep_claims_honest(self):
        for slug, page, title in pages.content_pages(self.states, self.verified_on):
            self.assertLessEqual(len(title), 70)
            # Search engines cut the snippet around here, and the state pages are already
            # held to this; the hand-written pages were not, and two had drifted over.
            description = page.split('<meta name="description" content="', 1)[1].split('">', 1)[0]
            self.assertLessEqual(len(description), 165, slug)
            self.assertNotIn("DMV approved", page)
            self.assertNotIn("DMV-approved", page)
            self.assertIn("not legal advice", page)
            self.assertIn("ct=", page)
        _, comparison, _ = pages.comparison_hub_page(self.verified_on)
        self.assertIn("Disclosure", comparison)
        self.assertIn(pages.COMPETITOR_SNAPSHOT_DATE, comparison)
        _, texas, _ = pages.texas_deep_page(self.states["TX"], self.verified_on)
        self.assertIn("2 hours per day", texas)
        self.assertIn("DES150N", texas)
        _, florida, _ = pages.florida_deep_page(self.states["FL"], self.verified_on)
        self.assertIn("notary", florida)
        self.assertIn("first 3 months", florida)


    def test_state_pages_lead_with_the_answer_and_ask_real_questions(self):
        _, texas, _ = pages.state_page("TX", self.states["TX"], self.verified_on, self.states)
        self.assertIn("How many supervised driving hours does Texas require?", texas)
        self.assertIn("Texas requires 30 hours of supervised practice", texas)
        self.assertIn("at most 2 hours count on any one day", texas)
        self.assertIn("Can you log all the hours in a few long days in Texas?", texas)
        self.assertIn("application/ld+json", texas)
        self.assertIn('"@type": "FAQPage"', texas)

        _, arkansas, _ = pages.state_page("AR", self.states["AR"], self.verified_on, self.states)
        self.assertIn("What does the Arkansas learner permit require?", arkansas)
        self.assertIn("does not set a numeric supervised-practice minimum", arkansas)

    def test_faq_schema_matches_the_visible_questions(self):
        for code in ("CA", "TX", "NC", "MN"):
            state = self.states[code]
            visible, schema = pages.faq_block(state)
            self.assertTrue(visible and schema)
            payload = json.loads(
                schema.split(">", 1)[1].rsplit("</script>", 1)[0]
            )
            questions = [entry["name"] for entry in payload["mainEntity"]]
            self.assertEqual(len(questions), len(set(questions)))
            for question in questions:
                self.assertIn(question, pages.strip_tags(visible))

    def test_related_states_only_link_comparable_targets(self):
        block = pages.related_states("CA", self.states["CA"], self.states)
        self.assertIn("Same 50-hour target", block)
        self.assertNotIn("california-supervised-driving-hours", block)


    def test_matching_path_qualifier_only_where_the_night_target_varies(self):
        single = pages.night_varies_by_path({"night": 10})
        self.assertFalse(single)
        self.assertTrue(
            pages.night_varies_by_path({"night": 10, "conditional_target": {"night": 15}})
        )
        self.assertTrue(
            pages.night_varies_by_path(
                {"night": 10, "applicant_paths": [{"nightMinutes": 900}]}
            )
        )
        self.assertFalse(
            pages.night_varies_by_path(
                {"night": 10, "applicant_paths": [{"nightMinutes": 600}, {"nightMinutes": None}]}
            )
        )

        _, hawaii, _ = pages.state_page("HI", self.states["HI"], self.verified_on, self.states)
        self.assertIn("including 10 at night.", hawaii)
        self.assertNotIn("for the matching path", hawaii)

        # Montana's alternative course path really does change the night figure, Minnesota's
        # only changes the total, so only Montana invites the reader to pick a path.
        _, montana, _ = pages.state_page("MT", self.states["MT"], self.verified_on, self.states)
        self.assertIn("10 or 15 at night for the matching path", montana)

        _, minnesota, _ = pages.state_page("MN", self.states["MN"], self.verified_on, self.states)
        self.assertIn("including 15 at night.", minnesota)
        self.assertNotIn("for the matching path", minnesota)

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
        future["_meta"]["verified_on"] = (TODAY + datetime.timedelta(days=1)).isoformat()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            pages.load_states(self.write_fixture(future), today=TODAY)


if __name__ == "__main__":
    unittest.main()
