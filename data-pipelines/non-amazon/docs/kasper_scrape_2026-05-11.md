# Kasper Scrape Handoff - 2026-05-11

## Scope

- Merchant: `kasper_com`
- Triage rank: 10
- Triage URL: `https://www.kasper.com/collections/clothing/products/open-front-seamed-jacket-stretch-crepe-aqua-oasis`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_kasper_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/kasper_com/`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `kasper_com.claim` was present.
- Created active claims in both repo and data-root claim directories.
- No old `_claims/kasper_com.txt` history was present.

## Adapter And Coverage

- Adapter: `junip_product_level`
- Public review source: Junip product reviews API at `https://api.juniphq.com/en/v2/products/remote/{product_id}/reviews`
- Product discovery:
  - `products.json` pages: 250 + 250 + 206 products
  - Product sitemap: 706 product URLs
  - Reconciled products discovered: 706
  - Products scanned: 706
  - Products excluded from output: 0
- Review coverage:
  - Review pages scanned: 1,128
  - Product review count hints seen: 35,575
  - Paging was exhaustive for discovered products.
- Stop condition: no 429, captcha, WAF, or block response encountered.

## Changes

- Switched the output naming to the standard Amazon-schema filenames.
- Added explicit stop-on-block handling for 403/429 and common captcha/WAF/body block markers.
- Kept the existing Junip adapter and product discovery path.
- Added parsing for Junip survey height values formatted like `5:6`, which unlocked measurement qualification for customer image rows.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/kasper_com/kasper_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/kasper_com/kasper_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 42
- Distinct reviews: 25
- Distinct customer images: 42
- Distinct product URLs: 20
- Rows with product URL: 42
- Rows with customer image: 42
- Rows with ordered size: 37
- Rows with any measurement/profile text: 30
- Supabase-qualified rows: 30

## Validation

- `python3 -m py_compile data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_kasper_reviews.py` passed.
- CSV and summary metrics were cross-checked and matched.
- Numeric measurement fields had no malformed values in the generated CSV.
- Three sampled customer image URLs returned HTTP 200 JPEG responses.
- Three sampled product URLs returned HTTP 200 HTML responses.
