# MiracleSuit scrape - 2026-05-05

## Scope

- Retailer: MiracleSuit (`miraclesuit.com`)
- Step: non-Amazon Step 1 raw scraping data
- Adapter: Yotpo product-level reviews
- Output directory: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\miraclesuit_com`
- Access policy: public product and review pages only; no auth bypass; no captcha bypass; restricted or unavailable pages skipped; polite retries; 0.5 second request delay

## Product coverage

Product discovery reconciled Shopify `products.json` with the public product sitemap before scraping:

- `products.json` page 1: 250 products
- `products.json` page 2: 250 products
- `products.json` page 3: 250 products
- `products.json` page 4: 250 products
- `products.json` page 5: 67 products
- Product sitemap: 1,067 product URLs
- Reconciled product count: 1,067
- Sitemap URLs missing from `products.json`: 0

The scraper scanned all 1,067 discovered product pages.

## Review coverage

- Products discovered: 1,067
- Products scanned: 1,067
- Products excluded from output: 0
- Products with review-image rows: 116
- Review pages scanned: 1,412
- Yotpo review-count hint across scanned products: 83,122
- Exhaustive review paging: true
- Errors: 0

## Output

The scraper emits one row per unique shopper review image after deduping repeated review/photo combinations.

- Rows written: 44
- Distinct reviews: 38
- Distinct images: 44
- Distinct product URLs: 28
- Rows with customer image: 44
- Rows with product URL: 44
- Rows with any measurement: 8
- Rows with customer ordered size: 8
- Supabase-qualified rows: 8

Correction note:

- The first completed run populated measurements from review text but missed ordered sizes such as `Size 10 was perfect`, leaving qualified rows at 0.
- The MiracleSuit adapter was patched to extract ordered size from Yotpo `custom_fields` when available and from explicit review-text size phrases otherwise.
- The completed scrape output was corrected from the already scraped rows after a rerun attempt hit `429 Too Many Requests`; no additional high-frequency retrying was performed.

Outputs:

- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\miraclesuit_com\miraclesuit_com_reviews_matching_intake_schema.csv`
- Summary JSON: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\miraclesuit_com\miraclesuit_com_reviews_matching_intake_schema_summary.json`
