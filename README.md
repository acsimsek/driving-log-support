# drivinglog.acsimsek.com

Static site for Driving Log (GitHub Pages). `index.html`, `support.html` and `privacy.html`
are hand-edited. Everything under `guides/`, plus `sitemap.xml` and `robots.txt`, is
generated — do not edit those by hand.

## Regenerating the guides

```bash
python3 generate_pages.py
python3 -m unittest -v
git diff --exit-code
```

Reads `../driving-log-ios/states.json`. The generator publishes only whitelisted, user-facing
fields (internal research notes never reach a page), stamps every page with the rule data's
`verified_on` date, and **refuses to build** when that date is older than 90 days.
The tests also cover conditional hour paths, source/status validation, mailto encoding and
the fields that must never be published.

## Measurement

- iPhone CTAs use App Store Campaign Links: `web-home`, `compare-roadready`, and one
  `guide-xx` campaign per state page. The generator derives each state campaign from its
  two-letter code, so future guide pages are attributed automatically. Apple displays a
  campaign after at least five individual Apple Accounts install through its link.
- The Android waitlist is a mailto to support@acsimsek.com by design: the site itself collects
  nothing, so the privacy page stays honest. Waitlist volume is measured in the inbox.
