# Superfit Hero Scrape Handoff - 2026-05-11

## Scope

- Merchant: `superfithero_com`
- Triage rank: 15
- Triage URL: `https://www.superfithero.com`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_superfithero_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/superfithero_com/`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `superfithero_com.claim` was present.
- Created active claims in both repo and data-root claim directories.
- No old `_claims/superfithero_com.txt` history was present.
- Read the prior 2026-05-04 handoff and old local output as history only.

## Adapter And Coverage

- Adapter: Judge.me `reviews_for_widget`, product-level, sorted with pictures.
- Public review source: `https://api.judge.me/reviews/reviews_for_widget`
- Product discovery:
  - `products.json`: 92 products
  - Product sitemap: 92 product URLs
  - Reconciled products discovered: 92
  - Products scanned: 92
  - Products excluded from output: 2
- Review coverage:
  - Review pages scanned: 128
  - Product review count hints seen: 1,085
  - Products with review rows: 65
  - Paging was exhaustive for discovered products.
- Stop condition: no 429, captcha, WAF, or block response encountered.

## Findings

- Public Judge.me coverage is useful for customer images and product URLs, but most review-photo cards only expose `Fit Details: True to Size`.
- Ordered size appears only in a small number of custom-form answers, variant labels, or explicit review text.
- Measurements/profile text are similarly sparse and only available when the reviewer wrote them into public text.
- I inspected the raw Judge.me payload directly; there was no hidden public size/profile payload beyond the rendered review-card HTML already parsed by the adapter.

## Changes

- Switched output naming from the old intake-schema filenames to the standard Amazon-schema filenames.
- Added explicit stop-on-block handling for 403/429 and common captcha/WAF/body block markers.
- Corrected `rows_with_distinct_product_url` to report the distinct URL count rather than row count.
- Kept deterministic parsing only; no inferred size or measurement fields were guessed.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/superfithero_com/superfithero_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/superfithero_com/superfithero_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 190
- Distinct reviews: 157
- Distinct customer images: 190
- Distinct product URLs: 36
- Rows with product URL: 190
- Rows with customer image: 190
- Rows with ordered size: 11
- Rows with any measurement/profile text: 17
- Supabase-qualified rows: 3

## Validation

- `python3 -m py_compile data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_superfithero_reviews.py` passed.
- CSV and summary metrics were cross-checked and matched.
- Numeric measurement fields had no malformed values in the generated CSV.
- Three sampled customer image URLs returned HTTP 200 JPEG responses.
- Three sampled product URLs returned HTTP 200 HTML responses.
