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

# The only states.json fields a page may read. Everything else is internal.
PUBLIC_FIELDS = {
    "code", "name", "total", "total_minutes", "night", "night_minutes", "unit",
    "permit_days", "permit_months", "min_days", "daily_cap", "weekly_cap",
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


def slug_for(code: str, name: str) -> str:
    if code in SLUGS:
        return SLUGS[code]
    words = "".join(character.lower() if character.isalnum() else " " for character in name)
    name_slug = "-".join(words.split())
    return f"{name_slug}-supervised-driving-hours"


def humanize(value: str) -> str:
    return value.replace("_", " ")


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
    if s.get("night_definition"):
        rows.append(("Night means", s["night_definition"]))
    if s.get("permit_months"):
        rows.append(("Permit must be held", f"{s['permit_months']} months"))
    elif s.get("permit_days"):
        rows.append(("Permit must be held", f"{s['permit_days']} days"))
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
    return f"""
  <div class="cta">
    <a class="button" href="{esc(campaign_url(campaign))}">Download for iPhone</a>
    <a class="button secondary"
       href="{esc(mailto)}">Android — join the waitlist</a>
    <p class="fineprint">The waitlist is a plain email to us: it is used only to send one
    notification if an Android version ships, never shared, and deleted on request.</p>
  </div>"""


STYLE = """
    body { font: 17px/1.55 -apple-system, BlinkMacSystemFont, sans-serif; color: #17242a; margin: 0 auto; max-width: 760px; padding: 48px 20px 64px; }
    h1 { line-height: 1.2; color: #0f5963; }
    h2 { color: #0f5963; margin-top: 2em; }
    a { color: #0f5963; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #d8e2e4; vertical-align: top; }
    th[scope=row] { width: 45%; font-weight: 600; }
    .cta { margin: 2em 0; }
    .button { display: inline-block; background: #0f5963; color: #fff; padding: 12px 18px; border-radius: 10px; text-decoration: none; margin: 0 8px 8px 0; }
    .button.secondary { background: #fff; color: #0f5963; border: 1.5px solid #0f5963; }
    .fineprint, .sources, .disclaimer { font-size: 14px; color: #4a5a5f; }
    .disclaimer { border-top: 1px solid #d8e2e4; margin-top: 3em; padding-top: 1em; }
    nav { font-size: 15px; margin-bottom: 2em; }
    .guide-search { display: block; margin: 1.5em 0; }
    .guide-search span { display: block; font-weight: 600; margin-bottom: .4em; }
    .guide-search input { box-sizing: border-box; width: 100%; padding: 12px 14px; border: 1px solid #b7c7ca; border-radius: 10px; font: inherit; }
    .guide-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; padding: 0; }
    .guide-grid li { list-style: none; border: 1px solid #d8e2e4; border-radius: 12px; background: #f8fbfb; }
    .guide-grid a { display: block; padding: 13px 15px; font-weight: 600; text-decoration: none; }
    .comparison-card { margin-top: 2em; padding: 16px 18px; border-left: 4px solid #0f5963; background: #f1f7f7; }
"""

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


def page_shell(
    title: str,
    description: str,
    canonical: str,
    body: str,
    disclaimer: str = GENERAL_DISCLAIMER,
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
  <style>{STYLE}</style>
</head>
<body>
  <nav><a href="/">Driving Log</a> › <a href="/guides/">State guides</a></nav>
{body}
{disclaimer}
</body>
</html>
"""


def state_page(code: str, s: dict, verified_on: str) -> tuple[str, str, str]:
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
        title = f"{name} supervised driving: {total}"
        description = (
            f"{name} supervised driving rules: {total}"
            + (f"; {night} at night" if night else "")
            + ". Check permit timing, credited limits, log paperwork and official state sources."
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
        f"{name}: learner permit practice requirements"
        if s.get("no_hour_requirement")
        else f"{name}: supervised driving hours, explained"
    )
    body = f"""  <h1>{esc(heading)}</h1>
  <p>{editorial_paragraph(s)}</p>

  <h2>The requirement at a glance</h2>
  <table>
{requirement_rows(s)}
  </table>
{curfew}
{special_rules(s)}

  <h2>The paperwork</h2>
{form_para}
{required_fields}
{sources_block(s, verified_on)}

{extras}

  <h2>How Driving Log helps in {esc(name)}</h2>
  <p>Driving Log tracks each drive with its day and night minutes and, where {esc(name)} sets a
  numeric target, shows the time you drove beside the time that <em>counts</em> under the configured
  rules — with the reason whenever they differ. The core app is free, keeps everything on your device and private
  iCloud, and needs no account. A printable record of every entry is included; sourced worksheet
  layouts for several states are part of the one-time Pro upgrade.</p>
{cta_block(name, f"guide-{code.lower()}")}"""

    return slug, page_shell(title, description, canonical, body, STATE_DISCLAIMER), title


def comparison_page(verified_on: str) -> tuple[str, str, str]:
    slug = "roadready-alternative"
    title = "Looking for a RoadReady alternative? An honest comparison"
    description = (
        "Compare Driving Log with RoadReady for supervised driving: accounts, privacy, "
        "state-aware totals, pricing and importing an existing CSV log."
    )
    canonical = f"{BASE_URL}/guides/{slug}.html"
    body = f"""  <h1>Looking for a RoadReady alternative?</h1>
  <p>RoadReady is the best-known supervised-driving log and many state programs recommend it.
  If it works for your family, keep using it. This page is for families who want a different
  trade-off — and it sticks to facts we can stand behind.</p>

  <h2>What Driving Log does differently</h2>
  <table>
      <tr><th scope="row">Account</th><td>None. No sign-up, no login. Your log lives on your
      device and in your private iCloud.</td></tr>
      <tr><th scope="row">Privacy label</th><td>&ldquo;Data Not Collected&rdquo; on the App
      Store: no analytics, no ads, no tracking SDKs.</td></tr>
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
{cta_block(None, "compare-roadready")}"""
    return slug, page_shell(title, description, canonical, body), title


def index_page(entries: list[tuple[str, str]]) -> str:
    comparison = next(entry for entry in entries if entry[0] == "roadready-alternative")
    state_entries = [entry for entry in entries if entry[0] != "roadready-alternative"]
    items = "".join(
        f'<li data-guide><a href="/guides/{slug}.html">{esc(title)}</a></li>'
        for slug, title in sorted(state_entries, key=lambda entry: entry[1])
    )
    body = f"""  <h1>State guides</h1>
  <p>Supervised-driving requirements for learner drivers in all 50 states and Washington, DC,
  summarised from official state sources with the verification date on every page.</p>
  <label class="guide-search"><span>Find your state</span>
    <input type="search" id="guide-filter" placeholder="Start typing a state name"
      autocomplete="off">
  </label>
  <ul class="guide-grid" id="guide-list">{items}</ul>
  <p class="comparison-card"><strong>Switching from another log?</strong><br>
    <a href="/guides/{comparison[0]}.html">{esc(comparison[1])}</a></p>
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
    for code, state in states.items():
        slug, html_text, title = state_page(code, state, verified_on)
        (OUT_DIR / f"{slug}.html").write_text(html_text, encoding="utf-8")
        entries.append((slug, title))
    slug, html_text, title = comparison_page(verified_on)
    (OUT_DIR / f"{slug}.html").write_text(html_text, encoding="utf-8")
    entries.append((slug, title))
    (OUT_DIR / "index.html").write_text(index_page(entries), encoding="utf-8")

    urls = [
        f"{BASE_URL}/",
        f"{BASE_URL}/support.html",
        f"{BASE_URL}/privacy.html",
        f"{BASE_URL}/guides/",
    ] + [
        f"{BASE_URL}/guides/{s}.html" for s, _ in entries
    ]
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
    print(f"Generated {len(entries)} guide pages + index + sitemap (rules verified {verified_on}).")


if __name__ == "__main__":
    main()
