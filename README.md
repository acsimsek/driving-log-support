# drivinglog.acsimsek.com

Static site for Driving Log (GitHub Pages). `index.html`, `support.html` and `privacy.html`
are hand-edited. Everything under `guides/`, plus `sitemap.xml` and `robots.txt`, is
generated — do not edit those by hand.

The guide build covers all 50 states plus Washington, DC. The seven original pilot URLs are
kept stable; every other jurisdiction uses a predictable
`guides/<state-name>-supervised-driving-hours.html` URL.

## Regenerating the guides

```bash
python3 generate_pages.py
python3 -m unittest -v
git diff --exit-code
```

Reads `../driving-log-ios/states.json`. The generator publishes only whitelisted, user-facing
fields (internal research notes never reach a page), stamps every page with the rule data's
`verified_on` date, and **refuses to build** when that date is older than 90 days. It also refuses
partial coverage, unverified jurisdictions, missing official sources and contradictory hour data.
The tests cover all 51 jurisdiction codes, unique metadata and slugs, conditional and staged hour
paths, no-hour exceptions, source/status validation, campaign attribution, mailto encoding and the
fields that must never be published.

## Measurement

- iPhone CTAs use App Store Campaign Links: `web-home`, `compare-roadready`, and one
  `guide-xx` campaign per state page. The generator derives each state campaign from its
  two-letter code, so future guide pages are attributed automatically. Apple displays a
  campaign after at least five individual Apple Accounts install through its link.
- The Android waitlist is a mailto to support@acsimsek.com by design: the site itself collects
  nothing, so the privacy page stays honest. Waitlist volume is measured in the inbox.

## Refreshing product screenshots

The homepage uses real simulator captures from the iOS repository, not hand-built mockups.
The 1.5 refresh (1 October 2026) uses these reviewed sources:

| Website asset | Source in `../driving-log-ios/` |
| --- | --- |
| `assets/dashboard.png` | `app-store/screenshots/candidate-1.5-2026-09-30/raw/store15-dashboard.png` |
| `assets/progress.png` | `app-store/screenshots/candidate-1.5-2026-09-30/raw/store15-counts.png` |
| `assets/pro.png` | `app-store/screenshots/candidate-1.5-2026-09-30/raw/store15-pro.png` |
| `assets/add-drive.png` | `app-store/design/review-1.5-2026-09-30/editor-dark.png` |

All four are real 1.5 dark-mode simulator screens with demo data. Dashboard and What counts
show Texas; the progress alt text must not call this California. No pixel content is retouched.
Resize proportionally with `sips --resampleWidth 720 SOURCE --out assets/NAME.png`, then
encode WebP with `cwebp -q 85 assets/NAME.png -o assets/NAME.webp`. The resulting images
are 720×1564; PNG remains the compatibility fallback. Homepage and generated guide image URLs
use `?v=1.5` so browsers request the refreshed assets instead of a cached old screenshot.

After the next app UI change, capture the approved screens in the iOS repo under its disk guard
and shared job lock. Update the source mapping, image dimensions, alt text and cache version;
regenerate guides, run the site tests and review desktop/mobile previews before publishing.
