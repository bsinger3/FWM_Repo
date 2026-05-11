# HSIA Life Scrape - 2026-05-11

## Scope

- Site: `hsialife.com`
- Claimed scrape: `hsialife_com`
- Adapter: `okendo_store_level_and_product_level`
- Public endpoints only:
  - Shopify `products.json`
  - Shopify product sitemap
  - Okendo store reviews feed
  - Okendo product reviews feed

## Adapter Updates

- Added immediate stop behavior for HTTP 429 and challenge-like responses.
- Added Okendo store-level review media extraction and merged it with deeper product-level paging.
- Expanded Okendo media parsing to support nested `imageUrls` fields as well as direct `fullSizeUrl`, `largeUrl`, `url`, and `thumbnailUrl`.
- Added deterministic review attribute parsing from Okendo product, rating, and reviewer attributes.
- Improved bra and apparel variant parsing:
  - `Black / 38 / DDD/F` -> color `Black`, size `38DDD/F`, band `38`, cup `DDD/F`
  - `34DDD / Black` -> size `34DDD`, color `Black`
  - `XXXL / Black` -> size `XXXL`, color `Black`
- Added product exclusion accounting for true out-of-scope items such as gift cards and bra accessories, without excluding HSIA bra collections that use names such as `Petals`.

## Coverage

- Products discovered: 605
- Products scanned: 605
- Products excluded from output: 23
- Store review pages scanned: 24
- Product-level review pages scanned: 317
- Total review pages scanned: 341
- Store reviews seen: 2,308
- Product-level reviews seen: 9,036
- Store media reviews seen: 70
- Product-level media images seen: 274
- Raw review-image row candidates before dedupe: 392
- Exhaustive review paging: yes
- Errors: none

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/hsialife_com/hsialife_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/hsialife_com/hsialife_com_reviews_matching_intake_schema_summary.json`

## Final Metrics

- Rows written: 118
- Distinct reviews: 70
- Distinct images: 118
- Rows with distinct product URL: 25
- Rows with any product URL: 91
- Rows with customer image: 118
- Rows with customer ordered size: 74
- Rows with at least one measurement: 30
- Supabase-qualified rows: 16

## Notes

- The store-level feed is useful for recent review media and variant data, but it exposed only 2,308 reviews. The product-level feed reaches the deeper historical review set and remains necessary for HSIA.
- Some grouped Okendo review rows do not expose a current product URL or handle for discontinued/sibling products. Those rows are retained because they have customer media and review context, but they do not qualify for Supabase insertion unless a product URL can be recovered later.
