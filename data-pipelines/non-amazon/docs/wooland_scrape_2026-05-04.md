# Wool& scrape - 2026-05-04

## Scope

- Retailer: Wool& (`wooland.com`)
- Step: non-Amazon Step 1 raw scraping data
- Adapter: Judge.me product-level `reviews_for_widget`
- Shopify shop domain: `wool-and.myshopify.com`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wooland_com`

## Product coverage

Product discovery reconciled Shopify `products.json` with the public product sitemap before scraping:

- `products.json` page 1: 250 products
- `products.json` page 2: 205 products
- Product sitemap: 455 product URLs
- Reconciled product count: 455
- Sitemap URLs missing from `products.json`: 0

The scraper scanned all 455 discovered products. Out-of-scope products were still scanned and counted with `skip_reason` values before row output.

## Review coverage

- Products discovered: 455
- Products scanned: 455
- Products excluded from output: 30
- Products with review-image rows: 418
- Review pages scanned: 984
- Judge.me review-count hint across scanned products: 14,159
- Exhaustive review paging: true
- Errors: 0

## Output

The scraper emits one row per unique shopper review image after removing duplicate Judge.me image variants such as alternate `w` parameters and duplicate review/photo combinations that appear across sibling color products.

- Rows written: 4,422
- Distinct reviews: 2,312
- Distinct images: 4,422
- Distinct product URLs: 302
- Rows with customer image: 4,422
- Rows with product URL: 4,422
- Rows with any measurement: 4,048
- Rows with customer ordered size: 689
- Supabase-qualified rows: 611

Outputs:

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wooland_com/wooland_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wooland_com/wooland_com_reviews_matching_intake_schema_summary.json`
