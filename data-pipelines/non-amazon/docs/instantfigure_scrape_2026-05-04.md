# InstantFigure scrape - 2026-05-04

## Scope

- Retailer: InstantFigure (`instantfigure.com`)
- Step: non-Amazon Step 1 raw scraping data
- Adapter: TargetBay product-level review widget
- Shopify shop domain: `instantfigureinc.myshopify.com`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/instantfigure_com`

## Product coverage

Product discovery reconciled Shopify `products.json` with the public product sitemap before scraping:

- `products.json` page 1: 250 products
- `products.json` page 2: 250 products
- `products.json` page 3: 156 products
- Product sitemap: 656 product URLs
- Reconciled product count: 656
- Sitemap URLs missing from `products.json`: 0

The scraper scanned all 656 discovered products and recorded per-product summaries. Out-of-scope products were counted after discovery and scan, not silently dropped.

## Review coverage

- Products discovered: 656
- Products scanned: 656
- Products excluded from output: 157
- Review pages scanned: 656
- TargetBay review-count hint across scanned products: 1,013
- Exhaustive review paging: true for the public TargetBay product-level widget response used by this site
- Errors: 0

## Output

TargetBay returned public review text and review-count hints, but product review image slots were either absent or the TargetBay `no-image` placeholder. The scraper filters those placeholders and emits only shopper/customer review image URLs, so this scrape produced an empty Step 1 CSV with the standard header row.

- Rows written: 0
- Distinct reviews: 0
- Distinct images: 0
- Distinct product URLs: 0
- Rows with customer image: 0
- Rows with product URL: 0
- Rows with any measurement: 0
- Rows with customer ordered size: 0
- Supabase-qualified rows: 0

Outputs:

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/instantfigure_com/instantfigure_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/instantfigure_com/instantfigure_com_reviews_matching_intake_schema_summary.json`
