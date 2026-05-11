# Babyboo Fashion Scrape Handoff - 2026-05-11

## Scope

- Merchant: `babyboofashion_com`
- Triage rank: 13
- Triage URL: `https://www.babyboofashion.com/en-us/products/shae-maxi-dress-sage`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_babyboo_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/babyboofashion_com/`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `babyboofashion_com.claim` was present.
- Created active claims in both repo and data-root claim directories.
- No old `_claims/babyboofashion_com.txt` history was present.

## Adapter And Coverage

- Adapter: Yotpo product reviews API.
- Public review source: `https://api-cdn.yotpo.com/v1/widget/{app_key}/products/{product_id}/reviews.json`
- Product discovery:
  - `products.json` pages: 250 + 250 + 250 + 250 + 250 + 250 + 166 products
  - Product sitemap: 1,664 product URLs
  - Reconciled products discovered: 1,666
  - Products scanned: 1,666
  - Products excluded from output: 216
- Review coverage:
  - Review pages scanned: 2,915
  - Product review count hints seen: 180,116
  - Raw review image occurrences before dedupe: 27,938
  - Image URLs filtered as invalid: 10
  - Paging was exhaustive for discovered products.
- Stop condition: no 429, captcha, WAF, or block response encountered.

## Changes

- Switched output naming from the old intake-schema filenames to the standard Amazon-schema filenames.
- Added explicit stop-on-block handling for 403/429 and common captcha/WAF/body block markers.
- Kept the existing Yotpo adapter, deterministic size extraction, deterministic measurement parsing, product discovery, product-scope skips, row dedupe, and image validation.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/babyboofashion_com/babyboofashion_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/babyboofashion_com/babyboofashion_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 6,161
- Distinct reviews: 4,675
- Distinct customer images: 6,161
- Distinct product URLs: 430
- Rows with product URL: 6,161
- Rows with customer image: 6,161
- Rows with ordered size: 6,133
- Rows with any measurement/profile text: 6,086
- Supabase-qualified rows: 6,065

## Validation

- `python3 -m py_compile data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_babyboo_reviews.py` passed.
- CSV and summary metrics were cross-checked and matched.
- Numeric measurement fields had no malformed values in the generated CSV.
- Three sampled customer image URLs returned HTTP 200 JPEG responses.
- Three sampled product URLs returned HTTP 200 HTML responses.
