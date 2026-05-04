# Holykitygirl scrape notes - 2026-05-04

## Scope

- Site: `https://holykitygirl.com`
- Adapter: Judge.me product-level widget API
- Shop domain: `holykitygirl.myshopify.com`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/holykitygirl_com`

## Product coverage

- Discovered products from `products.json`: 2,461
- Product sitemap URLs scanned: 2,461
- Reconciled products scanned: 2,461
- Products excluded from row output after scanning: 113 accessory-only products
- Review pages scanned: 2,461
- Exhaustive review paging: yes

## Output

- CSV: `holykitygirl_com_reviews_matching_intake_schema.csv`
- Summary: `holykitygirl_com_reviews_matching_intake_schema_summary.json`

Final metrics:

- Rows written: 165
- Distinct reviews: 163
- Distinct images: 165
- Distinct product URLs: 52
- Rows with customer image: 165
- Rows with product URL: 165
- Rows with any measurement: 5
- Rows with customer ordered size: 12
- Supabase-qualified rows: 4

## Notes

- The site briefly returned `429 Too Many Requests` during discovery after smoke probes. The scraper now backs off on `429` responses and records sitemap errors instead of aborting when the product list is already available from `products.json`.
- Measurement and size extraction are deterministic only: Judge.me custom fields, variant labels, and explicit regex matches in review text.
- Rows are one row per shopper review image. No catalog/product images are emitted.
