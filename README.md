# drivinglog.acsimsek.com

Static site for Driving Log (GitHub Pages). `index.html`, `support.html` and `privacy.html`
are hand-edited. Everything under `guides/`, plus `sitemap.xml` and `robots.txt`, is
generated — do not edit those by hand.

## Regenerating the guides

```bash
python3 generate_pages.py
```

Reads `../driving-log-ios/states.json`. The generator publishes only whitelisted, user-facing
fields (internal research notes never reach a page), stamps every page with the rule data's
`verified_on` date, and **refuses to build** when that date is older than 90 days.

## Measurement

- The iPhone CTA currently uses the plain App Store URL. When ready, create Campaign Links in
  App Store Connect (App Analytics → Campaign links) and replace `APP_STORE_URL` with the
  `pt`/`ct` parameterised link so downloads attribute per page. Note Apple hides download
  counts below a small threshold.
- The Android waitlist is a mailto to support@acsimsek.com by design: the site itself collects
  nothing, so the privacy page stays honest. Waitlist volume is measured in the inbox.
