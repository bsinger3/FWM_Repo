# Superfit Hero Scrape - 2026-05-04

## Scope

- Site: `https://superfithero.com`
- Retailer folder: `superfithero_com`
- Adapter: Judge.me `reviews_for_widget`, product-level
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_superfithero_reviews.py`
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/superfithero_com/superfithero_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/superfithero_com/superfithero_com_reviews_matching_intake_schema_summary.json`

## Product Coverage

- `products.json`: 94 products
- product sitemap: 94 products
- reconciled products: 94
- products scanned: 94
- products excluded from output: 2
- excluded reasons:
  - `out_of_scope_store_credit`
  - `out_of_scope_gift_card`
- review pages scanned: 131
- exhaustive review paging: `true`

## Output Metrics

- rows written: 190
- distinct reviews: 157
- distinct images: 190
- distinct product URLs: 36
- rows with distinct product URL: 190
- rows with customer image: 190
- rows with customer ordered size: 11
- rows with any measurement: 17
- rows Supabase-qualified: 3

## Notes

Superfit Hero's Judge.me widget exposes some grouped or migrated reviews across related legacy product URLs. The scraper preserves the review card's own `data-product-url` when present and dedupes by review/image, so rows are tied to the product URL supplied by the review feed rather than blindly assigned to the currently scanned Shopify product.

Size extraction is deterministic. It uses Judge.me custom-form answers such as `What's your Super-fit?: NovaFit | 5X` when present, then conservative ordered-size wording from the review text or variant label. Measurement extraction is deterministic regex-only.

The CSV and summary JSON were synced to `s3://fwm-scraping-data-briannasinger`.
