# Oliver Logan Scrape Handoff - 2026-05-11

## Scope

- Site: `https://oliverlogan.com`
- Retailer key: `oliverlogan_com`
- Triage rank: 8
- Triage hint: 988 visible reviews and 87 review/media hints on the sampled product page.
- Adapter: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_oliverlogan_reviews.py`
- Data root used for run: `/Users/briannasinger/Projects/FWM_Data`

## Coordination

- Active claim created in repo `_active_scrape_claims/oliverlogan_com.claim`.
- Active claim created in data-root `_active_scrape_claims/oliverlogan_com.claim`.
- No existing Oliver Logan active or completed claim note was present.

## Product Discovery

- `products.json`: 118 products from page 1.
- Product sitemap: 118 product URLs from `https://oliverlogan.com/sitemap_products_1.xml?from=2047819317315&to=9247153455319`.
- Reconciled final product count: 118.
- Products scanned: 118.
- Products excluded from output scope: 3 (`gift card` or `belt`).
- Product-level Judge.me review pages scanned: 122.
- Product-level review count hint total: 28,781.

## Public Review Coverage

- Public Judge.me product-level endpoint: `https://api.judge.me/reviews/reviews_for_widget`.
- Params included `product_id`, `sort_by=with_pictures`, and `shop_domain=oliver-logan.myshopify.com`.
- Product-level paging completed without 429/captcha/WAF.
- No aggregate-only fallback was used.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/oliverlogan_com/oliverlogan_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/oliverlogan_com/oliverlogan_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 320.
- Distinct reviews: 200.
- Distinct images: 320.
- Rows with distinct product URL count: 59 distinct URLs.
- Rows with product URL: 320.
- Rows with customer image: 320.
- Rows with ordered size: 100.
- Rows with at least one measurement: 120.
- Supabase-qualified rows: 68.

## Validation

- CSV and summary row counts match.
- Numeric normalized measurement fields are numeric or blank.
- Sample customer image URLs returned HTTP 200 image responses.
- Sample product URLs returned HTTP 200 product pages.
- `python3 -m py_compile` passed for the adapter.
