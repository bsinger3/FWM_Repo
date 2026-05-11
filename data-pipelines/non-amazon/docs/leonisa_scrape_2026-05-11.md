# Leonisa Scrape Handoff - 2026-05-11

## Scope

- Site: `https://www.leonisa.com`
- Retailer key: `leonisa_com`
- Triage rank: 2
- Triage hint: 3,006 visible reviews and 313 review/media hints on the sampled product page.
- Adapter: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_leonisa_reviews.py`
- Data root used for run: `/Users/briannasinger/Projects/FWM_Data`

## Coordination

- Active claim created in repo `_active_scrape_claims/leonisa_com.claim`.
- Active claim created in data-root `_active_scrape_claims/leonisa_com.claim`.
- No existing Leonisa active claim was present.
- No historical `_claims/leonisa_com` note was found.

## Product Discovery

- `products.json`: 176 products from page 1.
- Product sitemap: 176 product URLs from `https://www.leonisa.com/sitemap_products_1.xml?from=6844191342724&to=10309335285892`.
- Reconciled final product count: 176.
- Products scanned: 176.
- Products excluded from output scope: 25 men's or masculine products.
- Product-level Judge.me `with_pictures` pages scanned: 27.
- Product-level review count hint total: 80,567.

## Public Review Coverage

The original product-level Judge.me widget route was still scanned for every discovered product:

- `https://api.judge.me/reviews/reviews_for_widget`
- Params included `product_id`, `sort_by=with_pictures`, and `shop_domain=leonisa-usa.myshopify.com`.
- This path only exposed one media page for products with media and produced the same low image yield class as the previous adapter.

The improved adapter also probes the public Judge.me CDN all-reviews media endpoint:

- `https://cdn.judge.me/reviews/all_reviews_js_based`
- Params included `review_type=all-reviews`, `sort_by=with_media`, `per_page=100`, and `shop_domain=leonisa-usa.myshopify.com`.
- Page 1 returned 17 review cards and 24 raw picture-link markers.
- Page 2 returned empty HTML, so media paging was exhausted without 429/captcha/WAF.
- Normal non-media text review pages were not exhaustively crawled because Step 1 output requires review-image rows; this is recorded in the summary JSON as `review_paging_note`.

No 429, captcha, WAF, DataDome, or forbidden response was encountered during the completed run.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/leonisa_com/leonisa_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/leonisa_com/leonisa_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 17.
- Distinct reviews: 13.
- Distinct images: 17.
- Rows with distinct product URL count: 13 distinct URLs.
- Rows with product URL: 17.
- Rows with customer image: 17.
- Rows with ordered size: 1.
- Rows with at least one measurement: 0.
- Supabase-qualified rows: 0.

## Notes

- The public media reviews include product URLs and customer image URLs, but Leonisa/Judge.me does not publicly expose ordered variant titles on these review cards.
- Deterministic extraction found one explicit size from review text.
- Deterministic extraction found no height, weight, bust, waist, hips, or inseam values in the retained image-review text.
- Sample customer image URLs and product URLs were validated with HTTP 200 responses.
