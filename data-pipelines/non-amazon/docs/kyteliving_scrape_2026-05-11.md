# Kyte Living Scrape Handoff - 2026-05-11

## Scope

- Merchant: `kyteliving_com`
- Triage rank: 67
- Triage URL: `https://kyteliving.com/products/womens-ribbed-cami-dress-in-currant?variant=50410246275353`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_kyteliving_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/kyteliving_com/`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `kyteliving_com.claim` was present.
- No old `_claims/kyteliving_com.txt` history was present.
- No existing script, handoff doc, or local data output was present.
- Created active claims in both repo and data-root claim directories.

## Adapter And Coverage

- Adapter: `shopify_catalog_plus_okendo_store_media_feed`
- Shopify catalog source: `https://kyteliving.com/products.json`
- Okendo store id: `2891f42d-2971-48d7-a4fc-2d2265d8bb7f`
- Public review source: Okendo store reviews API sorted by `has_media desc`
- Product discovery:
  - `products.json` pages: 250 + 250 + 101 products
  - Products discovered: 601
  - Products scanned: 601
  - Products excluded from output: 596
- Review coverage:
  - Store feed pages scanned: 28
  - Reviews seen in store feed: 2,800
  - Media reviews seen in store feed: 2,598
  - Okendo product metadata endpoints enriched: 63
  - Paging was not exhaustive for all text-only reviews; the run intentionally stopped at the first media-sorted page with zero media reviews.
- Stop condition: `first_media_sorted_page_without_media`
- No 429, captcha, WAF, or block response was encountered.

## Notes

- The lead triage PDP returned HTTP 200, but the `.js` and `.json` product endpoints for the supplied handle returned 404, so the lead appears stale or retired.
- The site exposes Okendo review data publicly. Review rows include customer media, ordered size in `productAttributes`, and profile text such as height and weight.
- Many useful women’s-clothing reviews point to retired products. Okendo’s per-product public endpoint exposes canonical product URLs for those reviews, but sampled retired product URLs returned HTTP 404 on the live storefront. The CSV still records those public Okendo product URLs because they are the available product URL evidence for the review.

## Changes

- Added a Kyte Living scraper using Shopify catalog discovery plus the Okendo media-sorted store feed.
- Added stop-on-block handling for 403/429 and common captcha/WAF/body block markers.
- Added Okendo per-product metadata enrichment for reviews whose store-feed row omits `productUrl`.
- Added parsing of Okendo profile attributes for ordered size, height, weight, bust, waist, hips, age, and inseam.
- Filtered output to women’s clothing rows and excluded bedding, baby/kids, accessories, gift cards, and unknown non-women products.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/kyteliving_com/kyteliving_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/kyteliving_com/kyteliving_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 354
- Distinct reviews: 312
- Distinct customer images: 354
- Distinct product URLs: 61
- Rows with product URL: 354
- Rows with customer image: 354
- Rows with ordered size: 351
- Rows with any measurement/profile text: 144
- Supabase-qualified rows: 144

## Validation

- `python3 -m py_compile data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_kyteliving_reviews.py` passed.
- CSV and summary metrics were cross-checked and matched.
- Numeric measurement fields had no malformed values in the generated CSV.
- Three sampled customer image URLs returned HTTP 200.
- Three sampled product URLs from Okendo product metadata returned HTTP 404 because those reviewed products appear retired; this is documented as a storefront freshness caveat rather than a scrape block.
