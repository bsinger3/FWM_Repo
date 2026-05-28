# No! Jeans scrape notes - 2026-05-27

## Scope

- Retailer: `nojeans_co`
- Source of truth: `sovrn_commerce_scrape_triage_candidates.csv`
- Triage fields: first-pass candidate, CPA+CPC, reviews present, photo review status `unknown_sample_too_small`, shipping `AU|CA|DE|ES|FR|GB|IT|NZ|US`, provider unknown, payout fields not populated.
- Seed evidence:
  - `https://nojeans.co/#main-content`
  - `https://nojeans.co/products/nj-20s01-knit-cardigan`
  - `https://nojeans.co/products/nj-25s06-surfing`

## Public implementation findings

- Product pages are public Next.js pages with Apollo state embedded in `__NEXT_DATA__`.
- Review implementation appears custom/internal: embedded `ProductReview` objects include `title`, `body`, `nickname`, `location`, `rating`, `sizeBought`, `colorBought`, `height`, and `createdAt`.
- No customer review image/media fields were exposed in sampled or full sitemap PDP state.
- Product/catalog images, colors, category, fabric, and available size options are exposed in the same public Apollo state. Because customer photos were not exposed, the scraper emits `image_source_type=catalog_model_image`.
- No Yotpo, Loox, Judge.me, Stamped, Okendo, WAF, auth wall, captcha, or 429 behavior was observed.

## Scraper

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_nojeans_reviews.py`
- Adapter: `next_apollo_catalog_model_images`
- Public sources used:
  - `https://nojeans.co/sitemap.xml`
  - Public No! Jeans PDP HTML and embedded Next/Apollo state
- Access policy: public pages only; stop on 429/captcha/WAF/auth behavior.

## Output

- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/nojeans_co/nojeans_co_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/nojeans_co/nojeans_co_reviews_matching_intake_schema_summary.json`

Final summary:

- Product URLs scanned: 60
- Rows written: 229
- Distinct product URLs in output: 60
- Rows with image URL and product URL: 229
- Customer review image rows: 0
- Catalog/model image rows: 229
- Embedded text reviews observed: 37
- Embedded reviews with media fields: 0
- Embedded reviews with `sizeBought`: 36
- Embedded reviews with `height`: 36
- Errors: 0

Notes:

- Review size/height fields were not attached to catalog image rows because the embedded reviews did not expose corresponding customer photos.
- Catalog rows include available size options and product metadata in `product_detail_raw`.
