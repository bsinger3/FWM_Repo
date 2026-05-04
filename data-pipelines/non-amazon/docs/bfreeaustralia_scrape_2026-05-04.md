# B Free Australia Scrape - 2026-05-04

## Scope

- Site: `https://www.bfreeaustralia.com`
- Retailer folder: `bfreeaustralia_com`
- Adapter: Stamped product-level reviews
- Stamped store ID: `6990`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_bfreeaustralia_reviews.py`
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/bfreeaustralia_com/bfreeaustralia_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/bfreeaustralia_com/bfreeaustralia_com_reviews_matching_intake_schema_summary.json`

## Product Coverage

- `products.json`: 1,193 products across 5 pages
- reconciled products: 1,193
- products scanned: 1,193
- products excluded from output: 161
- excluded reasons:
  - `out_of_scope_accessory_or_hosiery`
  - `out_of_scope_accessory_or_hosiery_postprocess`
  - `out_of_scope_baby_or_kids`
  - `out_of_scope_free_gift`
  - `out_of_scope_gift_card`
  - `out_of_scope_returns`
- review pages scanned: 2,184
- exhaustive review paging: `true`

## Output Metrics

- rows written: 372
- distinct reviews: 298
- distinct images: 372
- distinct product URLs: 93
- rows with product URL: 372
- rows with customer image: 372
- rows with customer ordered size: 38
- rows with any measurement: 259
- rows Supabase-qualified: 30

## Notes

B Free Australia uses Stamped product-level review feeds. The scraper scans every Shopify product and excludes out-of-scope products only after counting them in the product summary.

Stamped groups review sets across related product families, so raw per-product review hints and photo occurrences are much larger than the final deduped output. The scraper dedupes by review/image and keeps the scanned product URL as product context.

The full scrape initially produced 419 deduped image rows. A postprocess pass removed 47 accessory, pad, tea, gift-wrap, waist-trainer, belt/corset, adhesive/booster-pad, and hosiery rows. The script exclusion list was updated to match the postprocess rules for future reruns.

The CSV and summary JSON were synced to `s3://fwm-scraping-data-briannasinger`.
