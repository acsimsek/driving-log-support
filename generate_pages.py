#!/usr/bin/env python3
"""Generates the state guide pages for drivinglog.acsimsek.com from states.json.

Contract, agreed 2 September 2026:
- Only whitelisted, user-facing fields ever reach a page. states.json also carries internal
  research notes (warning/correction/*_note/model_impact) and they must never be published.
- The build refuses to run when the rule data's verified_on is older than 90 days, and stamps
  the verification date visibly on every page. Publishing stale legal guidance silently is the
  one failure mode this site must not have.
- Every page names the official source it was checked against, says the app is not an official
  form and not legal advice, and shows two CTAs: the App Store link and an Android waitlist
  mailto (the site itself collects nothing; the email lands at the existing support address).
"""

from __future__ import annotations

import datetime
import html
import json
import pathlib
import sys
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parent
STATES_JSON = REPO.parent / "driving-log-ios" / "states.json"
OUT_DIR = REPO / "guides"
BASE_URL = "https://drivinglog.acsimsek.com"
APP_STORE_BASE_URL = "https://apps.apple.com/app/apple-store/id6797597475"
APP_STORE_PROVIDER_TOKEN = "129248493"
SUPPORT_EMAIL = "support@acsimsek.com"
FRESHNESS_LIMIT_DAYS = 90
# Cloudflare Web Analytics beacon token (25 September 2026 decision). Empty means no
# script is emitted; when set, privacy.html must describe the measurement too — the test
# enforces that pairing so the site never measures silently.
# GoatCounter site code (25 September 2026 decision): counts App Store button taps as
# events, which Cloudflare Web Analytics cannot. Empty means no script and no events.
GOATCOUNTER_SITE = "drivinglog"
CLOUDFLARE_BEACON_TOKEN = "0a7da5a914d54a14a60343bf8d327f9b"

# The only states.json fields a page may read. Everything else is internal.
PUBLIC_FIELDS = {
    "code", "name", "total", "total_minutes", "night", "night_minutes", "unit",
    "permit_days", "permit_months", "permit_additional_days", "permit_start_label",
    "daytime_minutes", "min_days", "daily_cap", "weekly_cap",
    "permit_days_adult", "permit_days_without_school",
    "supervisor_min_age", "supervisor_min_license_years",
    "output", "signature", "night_definition", "supervisor_note", "signer_note",
    "permit_curfew", "extra_requirements", "required_fields", "source", "secondary_source",
    "night_blackout_months", "digital_accepted",
    "no_hour_requirement", "counts_professional_instruction", "effective_from",
    "adult_path", "age_eighteen_path", "required_conditions",
}

CONDITIONAL_TARGET_FIELDS = {
    "condition", "total", "total_minutes", "night", "night_minutes",
}

ALTERNATIVE_REQUIREMENT_FIELDS = {
    "condition", "replaces_hour_target", "note",
}

MILESTONE_FIELDS = {
    "total", "night", "additional_total", "additional_night", "note",
}

APPLICANT_PATH_FIELDS = {
    "id", "title", "totalMinutes", "nightMinutes", "permitDays", "permitMonths",
    "requiresEducation", "effectiveFrom", "effectiveTo", "note",
}
STAGE_TARGET_FIELDS = {"total", "night", "holding_months", "no_hour_target"}

CATEGORY_FIELDS = {"name", "hours"}

EXPECTED_JURISDICTIONS = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
EXPECTED_JURISDICTION_COUNT = len(EXPECTED_JURISDICTIONS)

SLUGS = {
    "CA": "california-supervised-driving-hours",
    "TX": "texas-behind-the-wheel-hours",
    "FL": "florida-learners-permit-driving-hours",
    "NC": "north-carolina-driving-log-hours",
    "WI": "wisconsin-supervised-driving-hours",
    "MN": "minnesota-supervised-driving-log",
    "NV": "nevada-beginning-driver-experience-hours",
}

# One paragraph per state that a template cannot produce: the thing that actually trips
# families up, drawn from the verified rule data and the official form itself.
EDITORIAL = {
    "CA": (
        "California's DL 603 driving log is <strong>optional</strong> — what the DMV actually "
        "requires is the parent or guardian certifying the 50 hours by signing the instruction "
        "permit itself. Many families keep a log anyway, because the certification is a legal "
        "statement and a dated record is what backs it up."
    ),
    "TX": (
        "The detail most Texas families miss: only <strong>two hours per day</strong> of practice "
        "count toward the 30, no matter how long the drive actually was. It is printed on TDLR "
        "Form DES150N itself (rev. December 2024) — an app or a paper log that counts a longer "
        "day at face value overstates your progress."
    ),
    "FL": (
        "Florida's certification is sworn: the 50 hours are attested before a notary or a "
        "license examiner. The state's own log sheet classifies each drive simply as day or "
        "night, so keeping the night minutes separate as you go is what makes the final count "
        "defensible."
    ),
    "NC": (
        "North Carolina is one of the few states with a <strong>weekly cap</strong>: no more "
        "than 10 hours of the 60 may be logged in any one week, and the Level 1 permit must be "
        "held for 9 months. Cramming hours in the last month does not work here by design."
    ),
    "WI": (
        "Wisconsin's HS-303 log is provided \"for your convenience\" — the binding step is the "
        "parent certification of 50 hours (10 at night). A quirk worth knowing: an hour with a "
        "qualified instructor may count as two, up to five actual instructor hours."
    ),
    "MN": (
        "Minnesota is strict about paperwork: the DVS states that a log completed on "
        "<strong>any other document will not be accepted</strong>. Whatever you track hours "
        "with, the entries must end up on the official DVS Supervised Driving Log sheet. "
        "Completing the 90-minute parent awareness course lowers the target from 50 to 40 hours."
    ),
    "NV": (
        "Nevada's DLD130 log must be handwritten in blue or black ink with original signatures, "
        "and it splits every session into daytime and nighttime columns. Rural learners without "
        "reachable driver education have a different path: 100 hours instead of 50."
    ),
}


def editorial_paragraph(s: dict) -> str:
    code = s["code"]
    if code in EDITORIAL:
        return EDITORIAL[code]

    name = esc(s["name"])
    if s.get("no_hour_requirement"):
        permit = (
            f" The permit must still be held for {esc(s['permit_days'])} days."
            if s.get("permit_days")
            else ""
        )
        return (
            f"{name}'s cited graduated-licensing source does not set a numeric supervised-"
            f"practice-hour minimum.{permit} That makes the non-hour eligibility steps below "
            "especially important; an app total is a personal record, not a substitute for "
            "those state requirements."
        )

    conditional = s.get("conditional_target")
    if conditional:
        return (
            f"{name} has more than one practice-hour path. The standard target is "
            f"<strong>{esc(s['total'])} hours</strong>, while the qualifying path described "
            f"below changes it to <strong>{esc(conditional['total'])} hours</strong>. Record "
            "which path applies before relying on the lower or higher total."
        )

    milestones = s.get("milestone")
    if milestones:
        return (
            f"{name} splits supervised practice across licence stages rather than treating "
            f"the <strong>{esc(s['total'])}-hour</strong> total as one undifferentiated bucket. "
            "The stage notes below matter because time may need to be completed before a "
            "particular application step."
        )

    if s.get("daily_cap") or s.get("weekly_cap"):
        cap = (
            f"{s['daily_cap']} hours per day"
            if s.get("daily_cap")
            else f"{s['weekly_cap']} hours per week"
        )
        return (
            f"{name} limits how quickly practice can be credited: no more than "
            f"<strong>{esc(cap)}</strong> counts. A longer drive can still be useful practice, "
            "but it should not make the state-progress total exceed that cap."
        )

    if s.get("categories") or s.get("required_conditions"):
        return (
            f"{name}'s rule is not only about reaching <strong>{esc(s['total'])} hours</strong>. "
            "Some of that practice must cover the particular conditions listed below, so a "
            "dated log should retain more detail than a single running total."
        )

    if s.get("output"):
        night = (
            f", including {esc(s['night'])} at night"
            if s.get("night")
            else ""
        )
        return (
            f"For {name}, the practical finish line is not just recording "
            f"<strong>{esc(s['total'])} supervised hours{night}</strong>; it is being able to "
            "complete the state's proof or certification described below. Keep dates and "
            "day/night time as you go so the final paperwork is supportable."
        )

    night = (
        f", including {esc(s['night'])} at night"
        if s.get("night")
        else ""
    )
    return (
        f"{name} requires <strong>{esc(s['total'])} hours of supervised practice{night}</strong>. "
        "The official source linked below controls; keep a dated record throughout the permit "
        "period instead of reconstructing the total at the end."
    )


def fail(message: str) -> None:
    print(f"BUILD BLOCKED: {message}", file=sys.stderr)
    sys.exit(1)


def load_states(
    states_json: pathlib.Path = STATES_JSON,
    today: datetime.date | None = None,
) -> tuple[dict, str]:
    data = json.loads(states_json.read_text(encoding="utf-8"))
    verified_on = data["_meta"]["verified_on"]
    verified_date = datetime.date.fromisoformat(verified_on)
    age = ((today or datetime.date.today()) - verified_date).days
    if age < 0:
        fail(f"states.json has a future verification date: {verified_on}.")
    if age > FRESHNESS_LIMIT_DAYS:
        fail(
            f"states.json was last verified {verified_on} ({age} days ago, limit "
            f"{FRESHNESS_LIMIT_DAYS}). Re-verify the rule data before publishing guidance."
        )
    states = {}
    for state in data["states"]:
        code = state["code"]
        if code in states:
            fail(f"states.json contains duplicate jurisdiction code {code}.")
        if state.get("status") != "verified":
            fail(f"{code} cannot be published because it is not status=verified.")
        if not state.get("source"):
            fail(f"{code} needs an official source before it can be published.")
        if not state.get("no_hour_requirement") and not state.get("total"):
            fail(f"{code} needs a positive total or no_hour_requirement=true.")
        if state.get("no_hour_requirement") and state.get("total"):
            fail(f"{code} cannot have both total and no_hour_requirement=true.")

        published = {k: v for k, v in state.items() if k in PUBLIC_FIELDS}
        if "applicant_paths" in state:
            published["applicant_paths"] = [
                {k: v for k, v in path.items() if k in APPLICANT_PATH_FIELDS}
                for path in state["applicant_paths"]
            ]
        if "stage_targets" in state:
            published["stage_targets"] = {
                stage: {k: v for k, v in value.items() if k in STAGE_TARGET_FIELDS}
                for stage, value in state["stage_targets"].items()
            }
        conditional = state.get("conditional_target")
        if conditional is not None:
            if not isinstance(conditional, dict) or not conditional.get("condition"):
                fail(f"{code} has an invalid conditional_target.")
            published["conditional_target"] = {
                k: v for k, v in conditional.items() if k in CONDITIONAL_TARGET_FIELDS
            }
        alternative = state.get("alternative_requirement")
        if alternative is not None:
            if not isinstance(alternative, dict) or not alternative.get("condition"):
                fail(f"{code} has an invalid alternative_requirement.")
            published["alternative_requirement"] = {
                k: v for k, v in alternative.items() if k in ALTERNATIVE_REQUIREMENT_FIELDS
            }
        milestones = state.get("milestone")
        if milestones is not None:
            if not isinstance(milestones, dict):
                fail(f"{code} has invalid milestones.")
            published["milestone"] = {
                key: {k: v for k, v in value.items() if k in MILESTONE_FIELDS}
                for key, value in milestones.items()
                if isinstance(value, dict)
            }
        categories = state.get("categories")
        if categories is not None:
            if not isinstance(categories, list):
                fail(f"{code} has invalid categories.")
            published["categories"] = [
                {k: v for k, v in category.items() if k in CATEGORY_FIELDS}
                for category in categories
                if isinstance(category, dict)
            ]
        for source_key in ("source", "secondary_source"):
            source = published.get(source_key)
            if source is not None and not source.startswith("https://"):
                fail(f"{code} {source_key} must use HTTPS.")
        states[code] = published
    found_codes = set(states)
    if found_codes != EXPECTED_JURISDICTIONS:
        missing = sorted(EXPECTED_JURISDICTIONS - found_codes)
        extra = sorted(found_codes - EXPECTED_JURISDICTIONS)
        fail(
            f"Expected all 50 states plus Washington, DC "
            f"({EXPECTED_JURISDICTION_COUNT} jurisdictions); missing={missing}, extra={extra}."
        )
    return states, verified_on


def esc(value) -> str:
    return html.escape(str(value))


def hours(state: dict, key: str) -> str:
    value = state.get(key)
    return f"{value} hours" if value is not None else "—"


def target_hours(s: dict) -> str:
    if s.get("no_hour_requirement"):
        return "no state-set hour minimum"
    totals = {s.get("total")}
    if s.get("conditional_target"):
        totals.add(s["conditional_target"].get("total"))
    values = sorted(value for value in totals if value is not None)
    return " or ".join(str(value) for value in values) + " hours"


def target_night_hours(s: dict) -> str:
    values = {s.get("night")}
    conditional = s.get("conditional_target") or {}
    if conditional.get("night") is not None:
        values.add(conditional["night"])
    return " or ".join(str(value) for value in sorted(v for v in values if v is not None))


def night_varies_by_path(s: dict) -> bool:
    """True only when the night figure itself differs between paths.

    "10 at night for the matching path" invites the reader to pick a path. On a page that shows a
    single night target there is nothing to pick, so the qualifier is dropped.
    """
    if " or " in target_night_hours(s):
        return True
    default = s.get("night")
    for path in s.get("applicant_paths") or []:
        minutes = path.get("nightMinutes")
        if minutes is None:
            continue
        if default is None or minutes != default * 60:
            return True
    return False


def slug_for(code: str, name: str) -> str:
    if code in SLUGS:
        return SLUGS[code]
    words = "".join(character.lower() if character.isalnum() else " " for character in name)
    name_slug = "-".join(words.split())
    return f"{name_slug}-supervised-driving-hours"


def humanize(value: str) -> str:
    return value.replace("_", " ")


def holding_period(s: dict) -> str:
    if s.get("permit_months"):
        period = f"{s['permit_months']} calendar months"
        if s.get("permit_additional_days"):
            period += f" plus {s['permit_additional_days']} day"
        return period
    return f"{s['permit_days']} days" if s.get("permit_days") else ""


def holding_anchor(s: dict) -> str:
    return s.get("permit_start_label") or ("Permit validation after the knowledge test" if s["code"] == "NJ" else "Permit issue date")


def requirement_rows(s: dict) -> str:
    if s.get("no_hour_requirement"):
        rows = [
            (
                "State-set practice-hour minimum",
                "No numeric minimum is stated in the cited graduated-licensing source",
            )
        ]
    else:
        rows = [("Supervised practice required", hours(s, "total"))]
    conditional = s.get("conditional_target")
    if conditional and conditional.get("total") is not None:
        condition = conditional["condition"]
        condition = condition[:1].lower() + condition[1:]
        value = f"{conditional['total']} hours"
        conditional_night = conditional.get("night")
        if conditional_night is not None and conditional_night != s.get("night"):
            value += f", including {conditional_night} at night"
        rows.append(
            (
                f"If {condition}",
                value,
            )
        )
    if s.get("night"):
        rows.append(("Of which at night", hours(s, "night")))
    if s.get("daytime_minutes"):
        rows.append(("Minimum daytime practice", f"{s['daytime_minutes'] / 60:g} hours; extra night hours do not replace daytime"))
    if s.get("night_definition"):
        rows.append(("Night means", s["night_definition"]))
    if holding_period(s):
        rows.append(("Default supervised period", holding_period(s)))
        rows.append(("Period starts", holding_anchor(s)))
    if s.get("applicant_paths"):
        rows.append(("Age / permit paths", "The default figures above vary by the applicant paths below. Select the matching path in the app."))
    if s.get("permit_days_without_school"):
        rows.append(
            (
                "Permit without driver school",
                f"{s['permit_days_without_school']} days",
            )
        )
    if s.get("min_days"):
        rows.append(("Practice on at least", f"{s['min_days']} different days"))
    if s.get("daily_cap"):
        rows.append(("Daily hours that count", f"max {s['daily_cap']} h/day"))
    if s.get("weekly_cap"):
        rows.append(("Weekly hours that count", f"max {s['weekly_cap']} h/week"))
    if (
        s.get("supervisor_min_age")
        or s.get("supervisor_min_license_years")
        or s.get("supervisor_note")
    ):
        details = []
        if s.get("supervisor_min_age"):
            details.append(f"age {s['supervisor_min_age']}+")
        if s.get("supervisor_min_license_years"):
            details.append(f"licensed {s['supervisor_min_license_years']}+ years")
        if s.get("supervisor_note"):
            details.append(s["supervisor_note"])
        rows.append(("Supervising adult", "; ".join(details)))
    if s.get("night_blackout_months"):
        rows.append(
            (
                "Learner-license driving window",
                f"daylight only for the first {s['night_blackout_months']} months",
            )
        )
    if s.get("digital_accepted"):
        rows.append(("Log copy accepted", "digital or printed"))
    if s.get("signature"):
        signature = {
            "single_certification": "one final certification",
            "per_entry": "a signature on each entry",
            "notarized": "a notarized certification",
        }.get(s["signature"], humanize(s["signature"]))
        rows.append(("Proof/signature model", signature))
    return "\n".join(
        f"      <tr><th scope=\"row\">{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows
    )


def special_rules(s: dict) -> str:
    sections: list[str] = []
    paths = s.get("applicant_paths", [])
    if paths:
        items = []
        for path in paths:
            dates = ""
            if path.get("effectiveFrom"):
                dates += f" Applies from {path['effectiveFrom']}."
            if path.get("effectiveTo"):
                dates += f" Applies through {path['effectiveTo']}."
            items.append(f"<li><strong>{esc(path['title'])}:</strong> {esc(path['note'])}{esc(dates)}</li>")
        sections.append("<h3>Choose the matching applicant path</h3><ul>" + "".join(items) + "</ul>")
    stages = s.get("stage_targets", {})
    stage_items = []
    for stage, target in stages.items():
        details = "No separate hour quota" if target.get("no_hour_target") else f"{target['total']} hours, including {target.get('night') or 0} at night"
        if target.get("holding_months"):
            details += f"; {target['holding_months']} calendar months from the intermediate/provisional license issue date"
        stage_items.append(f"<li>{esc(humanize(stage))}: {esc(details)}.</li>")
    if stage_items:
        sections.append("<h3>Current licence-stage requirements</h3><ul>" + "".join(stage_items) + "</ul>")
    milestones = s.get("milestone", {})
    if milestones:
        items = "".join(
            f"<li>{esc(details['note'])}</li>"
            for details in milestones.values()
            if details.get("note")
        )
        if items:
            sections.append(f"<h3>Stage-by-stage totals</h3><ul>{items}</ul>")

    categories = s.get("categories", [])
    if categories:
        items = "".join(
            f"<li>{esc(category['hours'])} hours in "
            f"{esc(humanize(category['name']))}</li>"
            for category in categories
            if category.get("name") and category.get("hours") is not None
        )
        if items:
            sections.append(f"<h3>Required conditions</h3><ul>{items}</ul>")

    conditions = s.get("required_conditions", [])
    if conditions:
        readable = ", ".join(humanize(condition) for condition in conditions)
        sections.append(
            "<p><strong>Practice conditions to include:</strong> "
            f"{esc(readable)}.</p>"
        )

    alternative = s.get("alternative_requirement")
    if alternative:
        note = alternative.get("note") or alternative["condition"]
        sections.append(f"<p><strong>Alternative path:</strong> {esc(note)}</p>")

    if s.get("age_eighteen_path"):
        sections.append(
            f"<p><strong>Age 18 path:</strong> {esc(s['age_eighteen_path'])}</p>"
        )
    if s.get("adult_path"):
        sections.append(f"<p><strong>Adult path:</strong> {esc(s['adult_path'])}</p>")
    return "\n".join(sections)


def sources_block(s: dict, verified_on: str) -> str:
    lines = [
        f'<a href="{esc(s["source"])}" rel="noopener">Official source</a>'
    ]
    if s.get("secondary_source"):
        lines.append(f'<a href="{esc(s["secondary_source"])}" rel="noopener">Additional official source</a>')
    links = " · ".join(lines)
    return (
        f'<p class="sources">{links}<br>'
        f"Requirements above were checked against these official sources on "
        f"<strong>{esc(verified_on)}</strong>. Rules change; always confirm with your state "
        f"before you rely on them.</p>"
    )


def stat_cards(s: dict) -> str:
    cards: list[tuple[str, str]] = []
    if s.get("no_hour_requirement"):
        cards.append(("No set minimum", "supervised hours in the cited source"))
    else:
        cards.append((target_hours(s).replace(" hours", ""), "supervised hours required"))
    if s.get("night"):
        label = (
            "night hours for the matching path"
            if night_varies_by_path(s)
            else "of those hours at night"
        )
        cards.append((target_night_hours(s), label))
    if s.get("permit_months"):
        cards.append((holding_period(s), "default supervised period"))
    elif s.get("permit_days"):
        cards.append((f"{s['permit_days']} days", "permit holding period"))
    if s.get("daily_cap"):
        cards.append((f"{s['daily_cap']} h/day", "maximum that counts"))
    elif s.get("weekly_cap"):
        cards.append((f"{s['weekly_cap']} h/wk", "maximum that counts"))
    elif s.get("min_days"):
        cards.append((str(s["min_days"]), "different practice days"))
    return "".join(
        f'<div class="stat"><b>{esc(value)}</b><span>{esc(label)}</span></div>'
        for value, label in cards
    )


def guide_summary(s: dict) -> str:
    if s.get("no_hour_requirement"):
        return "No set hour minimum"
    summary = target_hours(s)
    if s.get("night"):
        summary += f" · {target_night_hours(s)} at night"
    return summary


def campaign_url(campaign: str) -> str:
    query = urllib.parse.urlencode(
        {"pt": APP_STORE_PROVIDER_TOKEN, "ct": campaign, "mt": "8"}
    )
    return f"{APP_STORE_BASE_URL}?{query}"


def cta_block(state_name: str | None, campaign: str) -> str:
    subject_state = state_name or "state not entered"
    body_state = state_name or "[enter your state]"
    subject = f"Android waitlist — {subject_state}"
    body = (
        "I'd like to be notified once when Driving Log is available for Android. "
        "My state: {state}. (Your email is used only for that one notification, never shared, "
        "and deleted on request — just reply 'remove' any time.)".format(state=body_state)
    )
    mailto = "mailto:" + SUPPORT_EMAIL + "?" + urllib.parse.urlencode(
        {"subject": subject, "body": body}
    )
    where = f" in {esc(state_name)}" if state_name else ""
    return f"""
  <div class="cta-panel">
    <h2>Keep the log{where} with Driving Log</h2>
    <p>Free for one learner, no account, nothing collected. Every drive is stored on your iPhone and, when enabled, in your own private iCloud.</p>
    <div class="btn-row">
      <a class="btn" href="{esc(campaign_url(campaign))}">Download free for iPhone</a>
      <a class="btn secondary" href="{esc(mailto)}">Android — join the waitlist</a>
    </div>
    <p class="fineprint">The waitlist is a plain email to us: it is used only to send one
    notification if an Android version ships, never shared, and deleted on request.</p>
  </div>"""


STATE_DISCLAIMER = (
    '<p class="disclaimer">Driving Log is an independent app and this page is general '
    "information, not legal advice. The app does not produce official state forms and says so "
    "on every document it prints. Requirements are summarised from the official sources linked "
    "above and can change; your state's own instructions always take precedence.</p>"
)

GENERAL_DISCLAIMER = (
    '<p class="disclaimer">Driving Log is an independent app and this page is general '
    "information, not legal advice. Requirements can change; confirm current rules and forms "
    "with your state's licensing authority.</p>"
)


def analytics_snippet() -> str:
    if not CLOUDFLARE_BEACON_TOKEN:
        return ""
    return (
        '  <script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
        f"data-cf-beacon='{{\"token\": \"{CLOUDFLARE_BEACON_TOKEN}\"}}'></script>\n"
    )


def goatcounter_snippet() -> str:
    """Page views plus one event per App Store tap, keyed by the campaign code.

    Cookieless; the event path lets the dashboard show which page or campaign produced the
    tap without any personal data. Kept in one place so the privacy page can describe it.
    """
    if not GOATCOUNTER_SITE:
        return ""
    return (
        "  <script>\n"
        "    document.addEventListener('click', function (event) {\n"
        "      var link = event.target.closest && event.target.closest('a[href*=\"apps.apple.com\"]');\n"
        "      if (!link || !window.goatcounter || !window.goatcounter.count) { return; }\n"
        "      var campaign = (link.href.match(/[?&]ct=([^&]+)/) || [])[1] || 'unknown';\n"
        "      window.goatcounter.count({path: 'app-store-tap/' + campaign, title: document.title, event: true});\n"
        "    }, true);\n"
        "  </script>\n"
        f'  <script data-goatcounter="https://{GOATCOUNTER_SITE}.goatcounter.com/count" '
        'async src="//gc.zgo.at/count.js"></script>\n'
    )


def page_shell(
    title: str,
    description: str,
    canonical: str,
    body: str,
    disclaimer: str = GENERAL_DISCLAIMER,
    head_extra: str = "",
) -> str:
    return f"""<!doctype html>
<html lang="en-US">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{esc(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{esc(title)}">
  <meta property="og:description" content="{esc(description)}">
  <meta property="og:url" content="{esc(canonical)}">
  <meta property="og:image" content="{BASE_URL}/assets/icon-512.png">
  <link rel="icon" href="/assets/favicon.png" type="image/png">
  <link rel="apple-touch-icon" href="/assets/apple-touch-icon.png">
  <link rel="stylesheet" href="/site.css">
{head_extra}
{analytics_snippet()}{goatcounter_snippet()}</head>
<body>
  <header class="topbar">
    <div class="wrap">
      <a class="brand" href="/"><img src="/assets/favicon.png" alt="" width="30" height="30">Driving Log</a>
      <nav>
        <a href="/guides/">State guides</a>
        <a href="/support.html">Support</a>
        <a class="btn" href="{esc(campaign_url("web-nav"))}">Get the app</a>
      </nav>
    </div>
  </header>
{body}
  <div class="wrap narrow">
{disclaimer}
  </div>
  <footer>
    <div class="wrap">
      <a href="/">Home</a>
      <a href="/guides/">State guides</a>
      <a href="/support.html">Support</a>
      <a href="/privacy.html">Privacy Policy</a>
      <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a>
    </div>
  </footer>
</body>
</html>
"""


def direct_answer(s: dict) -> str:
    """The first sentence a searcher needs, before any explanation.

    People arrive from a question ("how many hours does Texas need?"). Burying the number under a
    paragraph of context costs the answer and the click, so the page leads with it and keeps the
    caveats underneath.
    """
    name = esc(s["name"])
    if s.get("no_hour_requirement"):
        held = (
            f" The learner permit must still be held for {esc(s['permit_days'])} days."
            if s.get("permit_days")
            else ""
        )
        return (
            f"<strong>{name} does not set a numeric supervised-practice minimum</strong> in the "
            f"graduated-licensing source cited below.{held} The other eligibility steps still apply."
        )
    parts = [f"<strong>{name} requires {esc(target_hours(s))} of supervised practice</strong>"]
    if s.get("night"):
        qualifier = " for the matching path" if night_varies_by_path(s) else ""
        parts.append(f"including {esc(target_night_hours(s))} at night{qualifier}")
    sentence = ", ".join(parts) + "."
    extra = []
    if s.get("daily_cap"):
        extra.append(f"at most {esc(s['daily_cap'])} hours count on any one day")
    if s.get("weekly_cap"):
        extra.append(f"at most {esc(s['weekly_cap'])} hours count in any one week")
    if s.get("min_days"):
        extra.append(f"practice has to fall on at least {esc(s['min_days'])} different days")
    if s.get("permit_months"):
        extra.append(f"the default supervised period is {esc(holding_period(s))}, starting at {esc(holding_anchor(s)).lower()}")
    elif s.get("permit_days"):
        extra.append(f"the permit must be held for {esc(s['permit_days'])} days")
    if extra:
        joined = extra[0] if len(extra) == 1 else ", ".join(extra[:-1]) + " and " + extra[-1]
        sentence += " On top of the total, " + joined + "."
    if s.get("daytime_minutes"):
        sentence += f" At least {s['daytime_minutes'] / 60:g} hours must be daytime practice."
    if s.get("applicant_paths"):
        sentence += " These are the default figures; age, permit date and course choices change the target as detailed below."
    return sentence


def faq_entries(s: dict) -> list[tuple[str, str]]:
    """Visible questions in the words people type, answered from the verified rule data.

    Google retired FAQ rich results in May 2026, so this is not markup chasing a snippet: the
    questions are here because they are the ones families actually ask, and assistants that read
    the page answer from them.
    """
    name = esc(s["name"])
    entries: list[tuple[str, str]] = []

    if s.get("no_hour_requirement"):
        entries.append((
            f"How many practice hours does {name} require?",
            f"The cited {name} source sets no numeric minimum. Keep a dated record anyway: it is "
            "the only evidence you have of what was practised and when.",
        ))
    else:
        answer = f"{name} requires {esc(target_hours(s))}"
        if s.get("night"):
            qualifier = " for the matching path" if night_varies_by_path(s) else ""
            answer += f", including {esc(target_night_hours(s))} at night{qualifier}."
        else:
            answer += "."
        if s.get("daytime_minutes"):
            answer += f" At least {s['daytime_minutes'] / 60:g} hours must be in daytime."
        if s.get("applicant_paths"):
            answer += " These are the default figures. Use the matching age and permit path below; some paths reduce or remove this quota."
        entries.append((f"How many driving hours do you need in {name}?", answer))

    if s.get("daily_cap"):
        entries.append((
            f"Can you log all the hours in a few long days in {name}?",
            f"No. {name} credits at most {esc(s['daily_cap'])} hours per day, so a longer drive "
            "still counts as that maximum. Spreading practice out is the only way to reach the total.",
        ))
    elif s.get("weekly_cap"):
        entries.append((
            f"Is there a weekly limit in {name}?",
            f"Yes. No more than {esc(s['weekly_cap'])} hours count in any one week, so the total "
            "cannot be crammed into the last month before applying.",
        ))

    if s.get("night_definition"):
        entries.append((
            f"What counts as night driving in {name}?",
            f"{name} defines it as {esc(s['night_definition'])}. Record the day and night parts of "
            "a drive separately as you go; splitting them afterwards is guesswork.",
        ))

    if s.get("permit_months"):
        entries.append((
            f"How long must the permit be held in {name}?",
            f"The default period is {esc(holding_period(s))}, starting at {esc(holding_anchor(s)).lower()}. Check the applicant and licence-stage paths below for exceptions.",
        ))
    elif s.get("permit_days"):
        entries.append((
            f"How long must the permit be held in {name}?",
            f"At least {esc(s['permit_days'])} days, counted from the date the permit was issued.",
        ))

    if s.get("output"):
        accepted = f"{name} names {esc(s['output'])}."
        if s.get("signature") == "notarized":
            accepted += " The certification is sworn before a notary or a license examiner."
        elif s.get("signature") == "per_entry":
            accepted += " Every entry needs the supervising adult's signature."
        if s.get("digital_accepted"):
            accepted += " A digital or printed copy is accepted."
        accepted += (
            " An app printout is a supporting record, not that official form; check the source "
            "below for what your office accepts."
        )
        entries.append((f"Does {name} accept a printed log from an app?", accepted))

    return entries[:5]


def faq_block(s: dict) -> tuple[str, str]:
    """Returns the visible FAQ markup and the matching JSON-LD, or two empty strings."""
    entries = faq_entries(s)
    if not entries:
        return "", ""
    items = "".join(
        f"<details><summary>{question}</summary><p>{answer}</p></details>"
        for question, answer in entries
    )
    visible = f'  <h2>Common questions</h2>\n  <div class="faq">{items}</div>'
    payload = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": html.unescape(strip_tags(question)),
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": html.unescape(strip_tags(answer)),
                },
            }
            for question, answer in entries
        ],
    }
    script = (
        '  <script type="application/ld+json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script>"
    )
    return visible, script


def strip_tags(value: str) -> str:
    out: list[str] = []
    depth = 0
    for character in value:
        if character == "<":
            depth += 1
        elif character == ">":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(character)
    return "".join(out)


def related_states(code: str, s: dict, states: dict) -> str:
    """Links to jurisdictions whose rule is genuinely comparable, not a random link farm."""
    if not states:
        return ""
    total = s.get("total")
    peers = [
        (other_code, other)
        for other_code, other in sorted(states.items(), key=lambda item: item[1]["name"])
        if other_code != code and other.get("total") == total and total is not None
    ][:4]
    if not peers:
        return ""
    links = " · ".join(
        f'<a href="/guides/{slug_for(other_code, other["name"])}.html">{esc(other["name"])}</a>'
        for other_code, other in peers
    )
    return (
        f'  <p class="sources"><strong>Same {esc(total)}-hour target:</strong> {links}</p>'
    )


def sheet_slug_for(name: str) -> str:
    words = "".join(character.lower() if character.isalnum() else " " for character in name)
    return "-".join(words.split()) + "-driving-log-sheet"


def sheet_link(name: str) -> str:
    return (
        f'<p class="sheet-link"><a href="/guides/{sheet_slug_for(name)}.html">Printable {esc(name)} '
        "driving log sheet</a> — a blank, dated log with day and night columns and a signature "
        "block. Print it or save it as a PDF.</p>\n"
    )


def inline_cta(state_name: str, campaign: str, headline: str) -> str:
    """A compact, above-the-fold download prompt with a real app screen.

    The full CTA panel stays at the end of the page; this one sits right after the direct
    answer so a reader who got what they came for sees the app before scrolling away.
    """
    return f"""
  <aside class="cta-inline no-print">
    <div>
      <h3>{esc(headline)}</h3>
      <p>Driving Log keeps the {esc(state_name)} rules, splits day and night minutes and prints a dated
      record with a signature block. Free for one learner, no account, nothing collected.</p>
      <a class="btn" href="{esc(campaign_url(campaign))}">Download free for iPhone</a>
    </div>
    <div class="phone"><picture><source srcset="/assets/progress.webp" type="image/webp"><img src="/assets/progress.png" alt="Driving Log progress screen with logged time, counted time and remaining requirements" width="720" height="1564" loading="lazy"></picture></div>
  </aside>"""


def detailed_guide_link(code: str) -> str:
    guides = {
        "TX": ("texas-30-hour-log-what-counts", "Texas 30-hour log: what counts toward the total"),
        "FL": ("florida-50-hour-log-notarized-certification", "Florida 50-hour log and notarized certification"),
    }
    if code not in guides:
        return ""
    slug, title = guides[code]
    return f'<p><a href="/guides/{slug}.html">{esc(title)}</a></p>\n'


def state_page(
    code: str,
    s: dict,
    verified_on: str,
    states: dict | None = None,
) -> tuple[str, str, str]:
    name = s["name"]
    slug = slug_for(code, name)
    total = target_hours(s)
    night = s.get("night")
    if s.get("no_hour_requirement"):
        title = f"{name} learner permit practice requirements"
        description = (
            f"{name} learner-permit practice rules, eligibility steps and official sources. "
            "Learn what to record when the cited GDL source sets no hour minimum."
        )
    else:
        title = f"{name} driving log: {total}" + (f", {night} at night" if night else "")
        description = (
            f"{name} driving log rules: {total}"
            + (f", {night} at night" if night else "")
            + ". Permit timing, what counts, the official paperwork, a printable log sheet "
            "and the state sources."
        )
    canonical = f"{BASE_URL}/guides/{slug}.html"

    extras = ""
    if s.get("extra_requirements"):
        items = "".join(f"<li>{esc(e)}</li>" for e in s["extra_requirements"])
        extras = f"<h2>Also required in {esc(name)}</h2>\n  <ul>{items}</ul>"

    curfew = ""
    if s.get("permit_curfew"):
        curfew = f"<p><strong>Permit-stage limit:</strong> {esc(s['permit_curfew'])}</p>"

    form_bits = [f"<strong>{esc(s['output'])}</strong>"] if s.get("output") else []
    if s.get("signer_note"):
        form_bits.append(esc(s["signer_note"]))
    form_para = (
        f"<p>{' — '.join(form_bits)}</p>"
        if form_bits
        else (
            "<p>The verified data does not name a separate state log form. Follow the "
            "official source below for the current proof and application instructions.</p>"
        )
    )

    required_fields = ""
    if s.get("required_fields"):
        items = "".join(f"<li>{esc(field)}</li>" for field in s["required_fields"])
        required_fields = (
            "<h3>State-specific details to preserve</h3>"
            f"<ul>{items}</ul>"
        )

    heading = (
        f"What does the {name} learner permit require?"
        if s.get("no_hour_requirement")
        else f"How many supervised driving hours does {name} require?"
    )
    faq_visible, faq_schema = faq_block(s)
    related = related_states(code, s, states or {})
    if s.get("permit_curfew"):
        curfew = f'<div class="callout warn"><strong>Permit-stage limit:</strong> {esc(s["permit_curfew"])}</div>'
    body = f"""  <section class="guide-hero">
    <div class="wrap narrow">
      <p class="crumbs"><a href="/">Driving Log</a> › <a href="/guides/">State guides</a> › {esc(name)}</p>
      <h1>{esc(heading)}</h1>
      <p class="lede">{direct_answer(s)}</p>
      <p class="crumbs">Checked against official {esc(name)} sources on {esc(verified_on)}.</p>
      <div class="stats">{stat_cards(s)}</div>
    </div>
  </section>
  <main class="wrap narrow prose">
  <div class="callout">{editorial_paragraph(s)}</div>

  <h2>What {esc(name)} asks for, line by line</h2>
  <table>
{requirement_rows(s)}
  </table>
{curfew}
{special_rules(s)}

  <h2>Which paperwork does {esc(name)} want?</h2>
{form_para}
{required_fields}
{sheet_link(name)}{detailed_guide_link(code)}{sources_block(s, verified_on)}

{extras}

  <h2>How does Driving Log help in {esc(name)}?</h2>
  <p>Driving Log tracks each drive with its day and night minutes and, where {esc(name)} sets a
  numeric target, shows the time you drove beside the time that <em>counts</em> under the configured
  rules — with the reason whenever they differ. The core app is free, keeps everything on your device and private
  iCloud, and needs no account. A printable record of every entry is included; sourced worksheet
  layouts for several states are part of the one-time Pro upgrade.</p>
{faq_visible}

{related}
{cta_block(name, f"guide-{code.lower()}")}
  <p class="state-nav"><a href="/guides/">← All state guides</a><a href="/guides/best-driving-log-apps-permit-hours.html">Compare logging apps →</a></p>
  </main>"""

    return (
        slug,
        page_shell(title, description, canonical, body, STATE_DISCLAIMER, head_extra=faq_schema),
        title,
    )


def comparison_page(verified_on: str) -> tuple[str, str, str]:
    slug = "roadready-alternative"
    title = "Looking for a RoadReady alternative? An honest comparison"
    description = (
        "Compare Driving Log with RoadReady for supervised driving: accounts, privacy, "
        "state-aware totals, pricing and importing an existing CSV log."
    )
    canonical = f"{BASE_URL}/guides/{slug}.html"
    body = f"""  <section class="guide-hero">
    <div class="wrap narrow">
      <p class="crumbs"><a href="/">Driving Log</a> › <a href="/guides/">State guides</a> › RoadReady comparison</p>
      <h1>Looking for a RoadReady alternative?</h1>
      <p class="lede">RoadReady is the best-known supervised-driving log and many state programs recommend it.
      If it works for your family, keep using it. This page is for families who want a different
      trade-off — and it sticks to facts we can stand behind.</p>
    </div>
  </section>
  <main class="wrap narrow prose">
  <h2>What Driving Log does differently</h2>
  <table>
      <tr><th scope="row">Account</th><td>None. No sign-up, no login. Your log lives on your
      device and in your private iCloud.</td></tr>
      <tr><th scope="row">Privacy</th><td>No ads or cross-app tracking. Version 1.3 adds optional basic usage analytics, off by default; driving records are never included.</td></tr>
      <tr><th scope="row">What counts vs. what you drove</th><td>Both numbers are shown side by
      side, with the reason whenever they differ — daily caps, night rules, permit dates. The
      state rule is cited from its official source, last verified {esc(verified_on)}.</td></tr>
      <tr><th scope="row">Recovery</th><td>Automatic on-device recovery points plus a
      checksummed JSON backup you keep yourself. A deleted drive stays recoverable for 30
      days.</td></tr>
      <tr><th scope="row">Price</th><td>Core tracking, sync, backups and the printable record
      are free. A one-time Pro purchase adds multiple learners, private iCloud family
      collaboration, CSV import and supported state worksheet layouts. No subscription.</td></tr>
  </table>

  <h2>Moving an existing log</h2>
  <p>If your current app can export drives as a <strong>CSV file</strong>, Driving Log can
  import it: it shows a preview first, adds nothing until you confirm, never creates
  duplicates, and lists any row it cannot read with its line number and the reason. Column
  names and date formats from common log exports are recognized automatically.</p>
  <p>We have not verified any specific app's export format, including RoadReady's — so we
  won't promise one-click migration. If your export doesn't import cleanly, email us the
  column headers (not your data) at <a href="mailto:{SUPPORT_EMAIL}">{SUPPORT_EMAIL}</a> and
  we'll look at supporting it.</p>

  <h2>Where RoadReady may fit better</h2>
  <p>RoadReady is free, long-established, and some state programs distribute materials built
  around it. Driving Log is currently iPhone-only, while RoadReady also offers an Android
  app. Check RoadReady's current listings on the
  <a href="https://apps.apple.com/us/app/roadready/id699534935" rel="noopener">App Store</a>
  and <a href="https://play.google.com/store/apps/details?id=com.saferoadsalliance.roadready"
  rel="noopener">Google Play</a>.</p>
{cta_block(None, "compare-roadready")}
  <p class="state-nav"><a href="/guides/">← All state guides</a></p>
  </main>"""
    return slug, page_shell(title, description, canonical, body), title


# Hand-written, evergreen-ish content pages. Numbers that describe our own app come from states.json
# (via the state dict); numbers about other apps are dated and labelled as observed on that day.
COMPETITOR_SNAPSHOT_DATE = "2026-09-17"
COMPETITORS = [
    # name, rating, count, price model, platforms, note
    ("RoadReady (Safe Roads Alliance)", "2.6", "16,200", "Free", "iPhone, Android",
     "Distributed through several state DMV parent programs. Reviews after the July 2026 rebuild "
     "describe login loops and lost hours; export a copy regularly whatever you use."),
    ("Student Driving Logger", "4.7", "5,900", "Free with ads; one-time ad removal", "iPhone",
     "GPS-based; some reviews mention distance errors and crashes while driving."),
    ("GoTime – Teen Driving Log", "4.8", "130", "Free", "iPhone", "Launched February 2026."),
    ("Student Driving Log", "4.8", "130", "Free", "iPhone", "Simple manual log."),
    ("DMV Driving Hours Log", "4.8", "20", "One-time purchase", "iPhone, Android",
     "Automatic night hours from sunset times."),
    ("Moda: Driving Permit Hours Log", "4.8", "17", "Free", "iPhone", "CarPlay and Siri start."),
    ("NSC DriveitHOME", "—", "—", "Free", "iPhone, Android",
     "From the National Safety Council; lesson ideas alongside the log."),
    ("Driving Log: Supervised Hours (this site)", "—", "no", "Free; one-time Pro",
     "iPhone", "No account; both parents log into one private iCloud record; rule citations for "
     "all 51 jurisdictions; signed printable record included free."),
]


def comparison_hub_page(verified_on: str) -> tuple[str, str, str]:
    slug = "best-driving-log-apps-permit-hours"
    title = "Best driving log apps for permit hours (2026)"
    description = (
        "An honest comparison of iPhone apps that track supervised driving hours for a learner "
        "permit: ratings, price, platforms and what each one does differently."
    )
    canonical = f"{BASE_URL}/guides/{slug}.html"
    rows = "".join(
        f'<div class="card"><h3>{esc(n)}</h3>'
        f'<p class="muted">{esc(r)} ★ · {esc(c)} ratings · {esc(pr)} · {esc(pl)}</p>'
        f"<p>{esc(note)}</p></div>"
        for n, r, c, pr, pl, note in COMPETITORS
    )
    body = f"""  <section class="guide-hero">
    <div class="wrap narrow">
      <p class="crumbs"><a href="/">Driving Log</a> › <a href="/guides/">State guides</a> › Best apps</p>
      <h1>Best driving log apps for permit hours</h1>
      <p class="lede">Written by the developer of one of the apps below, so read it as a map, not a verdict.
      Ratings and prices were read from the App Store on {esc(COMPETITOR_SNAPSHOT_DATE)} and change daily.</p>
    </div>
  </section>
  <main class="wrap narrow prose">
  <div class="callout"><strong>Disclosure.</strong> This site belongs to Driving Log, the last row in the table.
  Every other line is what the public App Store page showed on {esc(COMPETITOR_SNAPSHOT_DATE)}; we have not
  tested each competitor's export against a DMV counter, and none of the apps below, ours included,
  produces an official state form.</div>

  <h2>What to check before choosing any app</h2>
  <ul>
    <li><strong>Does it apply your state's rule?</strong> Texas credits at most 2 hours a day; North Carolina caps hours per week; Florida wants a notarized certification at the end. A running total alone can mislead you.</li>
    <li><strong>Can you get your data out?</strong> Whatever you use, export or print every few weeks. Several apps had update bugs this summer that lost hours.</li>
    <li><strong>Does your state accept a printout at all?</strong> Minnesota only accepts its own DVS form and Nevada only its DLD-130 form or the RoadReady app. In those states an app is a helper, not the paperwork.</li>
    <li><strong>Who else needs to log?</strong> If two parents supervise, check whether both can write to one record without sharing a password.</li>
  </ul>

  <h2>The apps side by side</h2>
  <div class="cards">
    {rows}
  </div>

  <h2>Where Driving Log fits</h2>
  <p>Driving Log is the newest entry in the list and has no ratings yet. What it does differently: there is no
  account, the record lives on your iPhone and in your own private iCloud, both parents can contribute to one
  log, every state rule links to the official page it came from (last verified {esc(verified_on)}), and the
  printable record with a signature block is free. The one-time Pro purchase adds extra learners, family
  collaboration and CSV import. It is iPhone-only today.</p>
  <p>If RoadReady or a state program already works for your family, keep using it. This page exists so you can
  compare on facts, and the <a href="/guides/roadready-alternative.html">RoadReady comparison</a> goes deeper on that one.</p>
{cta_block(None, "compare-best-apps")}
  <p class="state-nav"><a href="/guides/">← All state guides</a></p>
  </main>"""
    return slug, page_shell(title, description, canonical, body), title


def texas_deep_page(s: dict, verified_on: str) -> tuple[str, str, str]:
    slug = "texas-30-hour-log-what-counts"
    title = "Texas 30-hour driving log: the 2-hour daily cap and what counts"
    description = (
        "The Texas 30-hour log explained: only 2 hours per day count, 20 daytime and 10 night "
        "hours, the 6-month permit, form DES150N and a printable log sheet."
    )
    canonical = f"{BASE_URL}/guides/{slug}.html"
    body = f"""  <section class="guide-hero">
    <div class="wrap narrow">
      <p class="crumbs"><a href="/">Driving Log</a> › <a href="/guides/">State guides</a> › Texas 30-hour log</p>
      <h1>Texas 30-hour driving log: the 2-hour daily cap and what counts</h1>
      <p class="lede">Checked against TDLR's form and guide on {esc(verified_on)}.</p>
      <div class="stats">{stat_cards(s)}</div>
    </div>
  </section>
  <main class="wrap narrow prose">
  <div class="callout">Most Texas families find out late that <strong>only {esc(s["daily_cap"])} hours per day</strong>
  count toward the {esc(s["total"])}. A four-hour road trip is good practice, but it credits two hours on the
  log. At least 20 hours must be daytime and 10 hours nighttime. The current form sets no separate 30-day minimum.</div>
{inline_cta("Texas", "guide-tx-deep", "Track your Texas hours free on iPhone")}
  <h2>The five numbers</h2>
  <table>
    <tr><th scope="row">Supervised practice</th><td>{esc(s["total"])} hours, of which {esc(s["night"])} at night</td></tr>
    <tr><th scope="row">Daily credit cap</th><td>{esc(s["daily_cap"])} hours per day</td></tr>
    <tr><th scope="row">Minimum daytime practice</th><td>{s["daytime_minutes"] / 60:g} hours</td></tr>
    <tr><th scope="row">Learner license held</th><td>at least {esc(s["permit_months"])} months</td></tr>
    <tr><th scope="row">Supervising adult</th><td>age {esc(s["supervisor_min_age"])}+, licensed {esc(s["supervisor_min_license_years"])}+ years, signs each entry</td></tr>
  </table>

  <h2>The 30 hours are not the whole in-car requirement</h2>
  <p>The 30-hour log covers supervised practice. Texas driver education also has an in-car phase of 7 hours
  behind the wheel plus 7 hours of in-car observation with the instructor, and in parent-taught driver
  education (PTDE) the parent instructor is that instructor. Provider guides describe the combined
  requirement as 44 hours; the log form itself covers the 30. Confirm the current split with your course
  provider and the TDLR guide linked below.</p>

  <h2>The form: {esc(s["output"])}</h2>
  <p>{esc(s["signer_note"])}</p>
  <p>Fields the form asks for: {esc(", ".join(s["required_fields"]))}. Keep the date, the am/pm time and the
  day/night split for every drive as you go; reconstructing them at the end is where logs get rejected.</p>

  <h2>What an app should do for Texas</h2>
  <ul>
    <li>Apply the {esc(s["daily_cap"])}-hour daily cap automatically and show both the time you drove and the time that counts.</li>
    <li>Keep night minutes separate from day minutes.</li>
    <li>Check the 20-hour daytime minimum separately from the 10-hour nighttime minimum.</li>
    <li>Print a dated record you can copy onto, or attach to, the TDLR form. No app produces the official form itself.</li>
  </ul>
  <p>Driving Log does these four things for Texas and links the rule to its source. The full rule summary is on the
  <a href="/guides/texas-behind-the-wheel-hours.html">Texas guide</a>.</p>

  <h2>A filled-in example: how the daily cap changes the total</h2>
  <p>Four illustrative drives, logged the way the form asks. The last column is what Texas credits.</p>
  <table>
    <tr><th scope="col">Date</th><th scope="col">Time</th><th scope="col">Driven</th><th scope="col">Day / night</th><th scope="col">Counts</th></tr>
    <tr><td>Sat 14 Mar</td><td>9:10–10:00 am</td><td>50 min</td><td>day</td><td>50 min</td></tr>
    <tr><td>Sat 14 Mar</td><td>2:00–4:30 pm</td><td>2 h 30 min</td><td>day</td><td>1 h 10 min (day cap reached)</td></tr>
    <tr><td>Wed 18 Mar</td><td>8:40–9:20 pm</td><td>40 min</td><td>night</td><td>40 min</td></tr>
    <tr><td>Sun 22 Mar</td><td>10:00 am–1:00 pm</td><td>3 h</td><td>day</td><td>2 h</td></tr>
    <tr><th scope="row">Driven 7 h</th><td colspan="3"></td><td><strong>4 h 40 min counted</strong></td></tr>
  </table>

  <h2>Mistakes that get Texas logs questioned</h2>
  <ul>
    <li><strong>Counting a long drive at face value.</strong> A 3-hour drive credits 2 hours; a second drive the same day credits nothing once the cap is reached.</li>
    <li><strong>No am/pm, no day/night split.</strong> The form asks for both; a total without them cannot show the 20 daytime and 10 nighttime hours.</li>
    <li><strong>Missing adult signatures.</strong> Texas wants the supervising adult to sign each entry, not just the last page.</li>
    <li><strong>Mixing in the driver-education in-car hours.</strong> The 7 behind-the-wheel and 7 observation hours belong to the course record, not to the 30-hour log.</li>
    <li><strong>Reconstructing the log at the end.</strong> Dates and times written from memory are the entries examiners ask about.</li>
  </ul>
{sheet_link("Texas")}
{sources_block(s, verified_on)}
{cta_block("Texas", "guide-tx-deep")}
  <p class="state-nav"><a href="/guides/texas-behind-the-wheel-hours.html">← Texas guide</a><a href="/guides/">All state guides →</a></p>
  </main>"""
    return slug, page_shell(title, description, canonical, body, STATE_DISCLAIMER), title


def florida_deep_page(s: dict, verified_on: str) -> tuple[str, str, str]:
    slug = "florida-50-hour-log-notarized-certification"
    title = "Florida 50-hour driving log: night hours, notary and what counts"
    description = (
        "Florida's 50-hour log explained: 10 night hours, daylight-only driving for the first 3 "
        "months, the notarized certification and a printable log sheet."
    )
    canonical = f"{BASE_URL}/guides/{slug}.html"
    body = f"""  <section class="guide-hero">
    <div class="wrap narrow">
      <p class="crumbs"><a href="/">Driving Log</a> › <a href="/guides/">State guides</a> › Florida 50-hour log</p>
      <h1>Florida 50-hour driving log: night hours, notary and what counts</h1>
      <p class="lede">Checked against FLHSMV's driving log on {esc(verified_on)}.</p>
      <div class="stats">{stat_cards(s)}</div>
    </div>
  </section>
  <main class="wrap narrow prose">
  <div class="callout">Florida's certification is <strong>sworn</strong>: the {esc(s["total"])} hours are attested before a
  notary or a license examiner. That is why the day/night split matters from the first drive; the number you
  swear to should be one you can back up with dated entries.</div>
{inline_cta("Florida", "guide-fl-deep", "Track your Florida hours free on iPhone")}
  <h2>The rule in three lines</h2>
  <table>
    <tr><th scope="row">Supervised practice</th><td>{esc(s["total"])} hours, of which {esc(s["night"])} at night</td></tr>
    <tr><th scope="row">Learner license window</th><td>daylight only for the first {esc(s["night_blackout_months"])} months, so night hours come later in the year</td></tr>
    <tr><th scope="row">Supervising adult</th><td>age {esc(s["supervisor_min_age"])}+</td></tr>
  </table>

  <h2>The paperwork: {esc(s["output"])}</h2>
  <p>The state's own log sheet classifies each drive simply as day or night. Keep that split as you go, print
  the log, and bring it with the certification form to be signed in front of the notary or examiner. The
  printout from an app is a supporting record; the sworn certification is what the state accepts.</p>

  <h2>Planning the night hours</h2>
  <p>Because the first {esc(s["night_blackout_months"])} months are daylight-only, families who start in spring often reach 40 daytime
  hours quickly and then stall on the {esc(s["night"])} night hours. Put a few evening drives on the calendar as soon as the
  daylight-only period ends.</p>

  <h2>What an app should do for Florida</h2>
  <ul>
    <li>Keep night minutes separate and show how many of the {esc(s["night"])} remain.</li>
    <li>Warn about night entries dated inside the daylight-only window.</li>
    <li>Print a dated record you can attach to the certification. No app produces the official form.</li>
  </ul>
  <p>Driving Log does these for Florida and links the rule to its source. See the
  <a href="/guides/florida-learners-permit-driving-hours.html">Florida guide</a> for the full summary.</p>

  <h2>A filled-in example: what the log should look like</h2>
  <p>Four illustrative entries for a learner licensed on 2 March. Night drives only start once the
  first {esc(s["night_blackout_months"])} months are over.</p>
  <table>
    <tr><th scope="col">Date</th><th scope="col">Time</th><th scope="col">Driven</th><th scope="col">Day / night</th><th scope="col">Running total</th></tr>
    <tr><td>Sat 14 Mar</td><td>9:10–10:00 am</td><td>50 min</td><td>day</td><td>0 h 50 min day</td></tr>
    <tr><td>Sun 5 Apr</td><td>2:00–3:30 pm</td><td>1 h 30 min</td><td>day</td><td>2 h 20 min day</td></tr>
    <tr><td>Tue 9 Jun</td><td>8:45–9:30 pm</td><td>45 min</td><td>night</td><td>0 h 45 min night</td></tr>
    <tr><td>Thu 18 Jun</td><td>9:00–9:40 pm</td><td>40 min</td><td>night</td><td>1 h 25 min night</td></tr>
  </table>

  <h2>Mistakes that make the Florida certification hard to swear to</h2>
  <ul>
    <li><strong>Night entries inside the daylight-only window.</strong> A night drive dated in the first {esc(s["night_blackout_months"])} months contradicts the licence conditions.</li>
    <li><strong>Reaching 50 before reaching 10 at night.</strong> The night hours are a separate minimum; 45 day hours and 5 night hours is not done.</li>
    <li><strong>Signing the certification at home.</strong> It is sworn in front of the notary or the license examiner; sign it there.</li>
    <li><strong>A log with totals but no dates.</strong> The log is what backs up the sworn number; keep every entry dated.</li>
  </ul>
{sheet_link("Florida")}
{sources_block(s, verified_on)}
{cta_block("Florida", "guide-fl-deep")}
  <p class="state-nav"><a href="/guides/florida-learners-permit-driving-hours.html">← Florida guide</a><a href="/guides/">All state guides →</a></p>
  </main>"""
    return slug, page_shell(title, description, canonical, body, STATE_DISCLAIMER), title


def log_sheet_page(code: str, s: dict, verified_on: str) -> tuple[str, str, str]:
    """A blank, printable driving log for one state.

    Google's own query data for this site is dominated by "<state> driving log sheet" searches:
    families want paper. This page gives them a dated sheet built from the verified rule data,
    says plainly that it is not the state's form, and links the form and the app.
    """
    name = s["name"]
    slug = sheet_slug_for(name)
    title = f"{name} driving log sheet (printable)"
    description = (
        f"Free printable {name} driving log sheet: dated entries, day and night minutes and a "
        "supervising-adult signature block. Print it or save it as a PDF."
    )
    canonical = f"{BASE_URL}/guides/{slug}.html"
    guide = slug_for(code, name)

    if s.get("no_hour_requirement"):
        target_line = (
            f"{esc(name)}'s cited licensing source sets no numeric practice minimum; log the drives "
            "anyway so the record exists if it is asked for."
        )
    else:
        target_line = f"Target: <strong>{esc(target_hours(s))}</strong>"
        if s.get("night"):
            target_line += f", of which <strong>{esc(target_night_hours(s))} at night</strong>"
        if s.get("daytime_minutes"):
            target_line += f"; at least {s['daytime_minutes'] / 60:g} hours in daytime"
        target_line += "."
    rules = []
    if s.get("daily_cap"):
        rules.append(f"Only {esc(s['daily_cap'])} hours per day count toward the total.")
    if s.get("weekly_cap"):
        rules.append(f"Only {esc(s['weekly_cap'])} hours per week count toward the total.")
    if s.get("min_days"):
        rules.append(f"Practice on at least {esc(s['min_days'])} different days.")
    if s.get("night_definition"):
        rules.append(f"Night means {esc(s['night_definition'])}.")
    if s.get("night_blackout_months"):
        rules.append(f"Daylight-only driving for the first {esc(s['night_blackout_months'])} months of the permit.")
    if s.get("signature") == "per_entry":
        rules.append("The supervising adult signs each entry: use the initials column and sign the certification.")
    elif s.get("signature") == "notarized":
        rules.append("The state certification is sworn before a notary or examiner; this sheet is your supporting record.")
    rules_html = "".join(f"<li>{rule}</li>" for rule in rules)
    rules_block = f"<ul class=\"sheet-rules\">{rules_html}</ul>" if rules else ""

    form_line = (
        f"The official {esc(name)} paperwork is <strong>{esc(s['output'])}</strong>."
        if s.get("output")
        else f"The verified data does not name a separate {esc(name)} log form."
    )
    rows = "\n".join(
        "    <tr><td></td><td></td><td></td><td></td><td></td><td></td><td></td></tr>"
        for _ in range(18)
    )
    body = f"""  <section class="guide-hero">
    <div class="wrap narrow">
      <p class="crumbs"><a href="/">Driving Log</a> › <a href="/guides/">State guides</a> › <a href="/guides/{guide}.html">{esc(name)}</a> › Log sheet</p>
      <h1>{esc(name)} driving log sheet</h1>
      <p class="lede">{target_line}</p>
      <p class="crumbs">Built from official {esc(name)} sources checked on {esc(verified_on)}. Not an official state form.</p>
      <div class="sheet-actions no-print">
        <button class="btn" type="button" onclick="window.print()">Print or save as PDF</button>
        <a class="btn secondary" href="/guides/{guide}.html">Read the {esc(name)} rules</a>
      </div>
    </div>
  </section>
  <main class="wrap narrow prose sheet">
  <div class="callout">{form_line} This sheet is <strong>not an official form</strong>: it is a dated
  record you can keep as you go and copy onto, or attach to, whatever {esc(name)} asks for.
  <a href="{esc(s["source"])}" rel="noopener">Official source</a>.</div>
{rules_block}
  <div class="sheet-head">
    <div>Learner name</div><div>Permit / licence number</div>
    <div>Supervising adult</div><div>Adult licence number</div>
  </div>
  <table class="log">
    <tr><th scope="col">Date</th><th scope="col">Start</th><th scope="col">End</th><th scope="col">Total min</th><th scope="col">Night min</th><th scope="col">Road / weather</th><th scope="col">Adult initials</th></tr>
{rows}
    <tr><th scope="row">Page totals</th><td></td><td></td><td></td><td></td><td colspan="2"></td></tr>
  </table>
  <p class="sheet-cert">I confirm that the drives listed above took place as recorded and that I supervised them.</p>
  <div class="signature">
    <div>Supervising adult signature</div><div>Date</div>
    <div>Learner signature</div><div>Date</div>
  </div>
{inline_cta(name, f"sheet-{code.lower()}", "Skip the pen: the app keeps this log for you")}
  <p class="state-nav no-print"><a href="/guides/{guide}.html">← {esc(name)} guide</a><a href="/guides/">All state guides →</a></p>
  </main>"""
    return slug, page_shell(title, description, canonical, body, STATE_DISCLAIMER), title


def content_pages(states: dict, verified_on: str) -> list[tuple[str, str, str]]:
    return [
        comparison_hub_page(verified_on),
        texas_deep_page(states["TX"], verified_on),
        florida_deep_page(states["FL"], verified_on),
    ]


def index_page(entries: list[tuple[str, str, str]], verified_on: str) -> str:
    comparison = next(entry for entry in entries if entry[0] == "roadready-alternative")
    state_entries = [entry for entry in entries if entry[0] != "roadready-alternative"]
    items = "".join(
        f'<li data-guide><a href="/guides/{slug}.html"><strong>{esc(name)}</strong>'
        f"<span>{esc(summary)}</span></a></li>"
        for slug, name, summary in sorted(state_entries, key=lambda entry: entry[1])
    )
    body = f"""  <section class="guide-hero">
    <div class="wrap">
      <p class="crumbs"><a href="/">Driving Log</a> › State guides</p>
      <h1>Supervised driving hours by state</h1>
      <p class="lede">Hour targets, night rules, permit periods and paperwork for all 50 states and
      Washington, DC — summarised from official sources, last verified {esc(verified_on)}.</p>
    </div>
  </section>
  <main class="wrap page">
  <div class="finder">
    <label for="guide-filter"><strong>Find your state</strong></label>
    <input type="search" id="guide-filter" placeholder="Start typing a state name…" autocomplete="off">
    <ul class="guide-grid" id="guide-list">{items}</ul>
  </div>
  <section class="prose" aria-labelledby="practical-guides">
    <h2 id="practical-guides">Practical guides to logging your hours</h2>
    {detailed_guide_link("TX")}
    {detailed_guide_link("FL")}
    <p>Every state guide links a free printable driving log sheet with day and night columns and a signature block.</p>
  </section>
  <div class="callout" style="margin-top:28px"><strong>Choosing or switching apps?</strong>
    <a href="/guides/best-driving-log-apps-permit-hours.html">Best driving log apps for permit hours (2026)</a> ·
    <a href="/guides/{comparison[0]}.html">{esc(comparison[1])}</a></div>
  </main>
  <script>
    const filter = document.getElementById('guide-filter');
    const guides = [...document.querySelectorAll('[data-guide]')];
    filter.addEventListener('input', () => {{
      const query = filter.value.trim().toLowerCase();
      guides.forEach(item => {{
        item.hidden = !item.textContent.toLowerCase().includes(query);
      }});
    }});
  </script>"""
    return page_shell(
        "Supervised driving hour requirements by state",
        "State-by-state supervised driving hour requirements for learner permits, "
        "checked against official sources.",
        f"{BASE_URL}/guides/",
        body,
    )


def main() -> None:
    states, verified_on = load_states()
    OUT_DIR.mkdir(exist_ok=True)
    entries = []
    sheet_urls = []
    for code, state in states.items():
        slug, html_text, title = state_page(code, state, verified_on, states)
        (OUT_DIR / f"{slug}.html").write_text(html_text, encoding="utf-8")
        entries.append((slug, state["name"], guide_summary(state)))
        sheet_slug, sheet_html, _ = log_sheet_page(code, state, verified_on)
        (OUT_DIR / f"{sheet_slug}.html").write_text(sheet_html, encoding="utf-8")
        sheet_urls.append(f"{BASE_URL}/guides/{sheet_slug}.html")
    slug, html_text, title = comparison_page(verified_on)
    (OUT_DIR / f"{slug}.html").write_text(html_text, encoding="utf-8")
    entries.append((slug, title, ""))
    content_urls = []
    for slug, html_text, _ in content_pages(states, verified_on):
        (OUT_DIR / f"{slug}.html").write_text(html_text, encoding="utf-8")
        content_urls.append(f"{BASE_URL}/guides/{slug}.html")
    (OUT_DIR / "index.html").write_text(index_page(entries, verified_on), encoding="utf-8")

    urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/support.html",
        f"{BASE_URL}/privacy.html",
        f"{BASE_URL}/guides/",
    ] + [
        f"{BASE_URL}/guides/{entry[0]}.html" for entry in entries
    ] + content_urls + sheet_urls
    sitemap = "\n".join(
        ['<?xml version="1.0" encoding="UTF-8"?>',
         '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        + [f"  <url><loc>{u}</loc></url>" for u in urls]
        + ["</urlset>"]
    )
    (REPO / "sitemap.xml").write_text(sitemap + "\n", encoding="utf-8")
    (REPO / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}/sitemap.xml\n", encoding="utf-8"
    )
    print(f"Generated {len(entries)} guide pages + {len(sheet_urls)} log sheets + {len(content_urls)} content pages + index + sitemap (rules verified {verified_on}).")


if __name__ == "__main__":
    main()
