# Foxy Lingerie scrape notes - 2026-05-27

## Scope

- Retailer: `foxylingerie_com`
- Source of truth: `sovrn_commerce_scrape_triage_candidates.csv`
- Triage fields: first-pass candidate, CPC, reviews present, photo reviews present, shipping `US`, provider unknown, CPC amount not populated.
- Seed evidence:
  - `https://www.foxylingerie.com/collections/swimsuit-tops`
  - `https://www.foxylingerie.com/products/sunset-gradient-ring-bikini-set`
  - `https://www.foxylingerie.com/products/starfish-charm-scallop-bikini-set`

## Public implementation findings

- Product pages are custom Foxy Lingerie pages, not Shopify product JSON pages.
- PDPs expose a native/custom review block with `data-reviews-url`, e.g. `/products/<handle>/reviews`.
- The review endpoint is public when requested as XHR and returns JSON with `html` and `has_more`.
- The two Sovrn sample PDP review endpoints returned empty review HTML and a visible `No reviews yet` label.
- The broader public swimsuit category was scanned because the seed `swimsuit-tops` category only exposed the two empty sample products.
- Across 121 public swimsuit PDP review endpoints, all returned empty review HTML and no customer review images.
- Public PDPs expose catalog/model images plus size/color choices, so output uses `image_source_type=catalog_model_image`.
- No 429, captcha, WAF, or auth-wall behavior was observed.

## Scraper

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_foxylingerie_reviews.py`
- Adapter: `custom_reviews_endpoint_catalog_model_images`
- Public sources used:
  - `https://www.foxylingerie.com/collections/swimsuit-tops`
  - `https://www.foxylingerie.com/collections/sexy-swimsuits` pages 1-3
  - Public Foxy Lingerie PDP HTML
  - Public per-product XHR review endpoints
- Access policy: public pages/endpoints only; stop on 429/captcha/WAF/auth behavior.

## Output

- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/foxylingerie_com/foxylingerie_com_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/foxylingerie_com/foxylingerie_com_reviews_matching_intake_schema_summary.json`

Final summary:

- Product URLs scanned: 121
- Review endpoints scanned: 121
- Rows written: 585
- Distinct product URLs in output: 121
- Rows with image URL and product URL: 585
- Customer review image rows: 0
- Catalog/model image rows: 585
- Non-empty review endpoint responses: 0
- Errors: 0

Notes:

- This run preserves the triage source values in the summary JSON, but the public swimsuit scrape did not reproduce the `photo_reviews=yes` signal.
- Catalog rows include available size/color choices in `product_detail_raw`; customer size/fit measurements were not available from public review content.
