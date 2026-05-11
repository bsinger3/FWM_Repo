# wearfigs.com scrape - 2026-05-11

## Scope
- Retailer: `wearfigs_com`
- Site: `https://www.wearfigs.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_wearfigs_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wearfigs_com/`
- Scope policy: public sitemap product pages plus public FIGS GraphQL review data only; no auth bypass, no CAPTCHA bypass, stop on HTTP 403/429 or challenge-like responses.

## Method
- Discovered product handles from `https://www.wearfigs.com/sitemap.xml` and `sitemap-products.xml`.
- Parsed public product pages for Shopify product IDs, product title, color, model/product context, and page URL.
- Queried the public `/catalog/graphql` review endpoint with the same regional storefront headers exposed by the frontend.
- Used `filteredReviews` with `pictured: true` to preserve usable customer image rows without paging through non-image review inventory.
- Extracted ordered size from `Size Purchased` custom fields.
- Preserved reviewer profile/body text in `user_comment`, including Height, Weight, Occupation, and Fit fields when present.
- Converted only deterministic profile values through the shared intake parser. FIGS height bucket/range values such as `5'7 - 5'9` and `5'0 or less` were preserved in `user_comment` but cleared from exact height fields so no measurement was invented.

## Outputs
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wearfigs_com/wearfigs_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wearfigs_com/wearfigs_com_reviews_matching_intake_schema_summary.json`

## Coverage
- Product URLs in sitemap: 1,689 color-level URLs
- Unique product handles scanned: 387
- Target women clothing products scanned: 185
- Products excluded from output: 202
- Products with review rows: 83
- Review pages scanned: 89
- Public pictured-review count hint: 728
- Rows written: 917

## Required metrics
- Rows with distinct product URL: 83
- Rows with product URL: 917
- Rows with measurement: 770
- Rows with customer image: 917
- Rows with ordered size: 881
- Supabase-qualified rows: 769

## Validation
- `python3 -m py_compile data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_wearfigs_reviews.py`
- Full scrape completed without HTTP 403, HTTP 429, CAPTCHA, WAF, or challenge behavior.
- Summary validation reported zero invalid numeric fields for height, waist, hips, inseam, and bust.

## Notes
- Some FIGS sitemap products are accessories, footwear, stethoscopes, embroidery setup pages, gift cards, or men's items; these were scanned for context but excluded from output.
- Many seasonal and limited-collab product pages had zero pictured reviews. Core scrub products produced the high-signal qualified rows.
