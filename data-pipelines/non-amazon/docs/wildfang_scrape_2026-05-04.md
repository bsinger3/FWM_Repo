# Wildfang Scrape - 2026-05-04

## Scope

- Site: `https://www.wildfang.com`
- Retailer folder: `wildfang_com`
- Adapter: Okendo product-level reviews
- Okendo store ID: `5c043363-b18d-4bda-8184-c69c4fc0968e`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_wildfang_reviews.py`
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wildfang_com/wildfang_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wildfang_com/wildfang_com_reviews_matching_intake_schema_summary.json`

## Product Coverage

- `products.json`: 196 products
- product sitemap: 196 products
- reconciled products: 196
- products scanned: 196
- products excluded from output: 23
- excluded reasons:
  - `out_of_scope_accessory`
  - `out_of_scope_gift_card`
  - `out_of_scope_pet_item`
  - `out_of_scope_shipping_protection`
- review pages scanned: 428
- exhaustive review paging: `true`

## Output Metrics

- rows written: 383
- distinct reviews: 285
- distinct images: 383
- distinct product URLs: 80
- rows with product URL: 383
- rows with customer image: 383
- rows with customer ordered size: 168
- rows with any measurement: 188
- rows Supabase-qualified: 155

## Notes

Wildfang uses Okendo product-level review feeds keyed by Shopify product ID. Okendo returns grouped review sets across many related product/color URLs, so the raw product review count hint is much larger than the final deduped output. The scraper dedupes by review/image and preserves the Okendo `productUrl` when present.

Accessory, pet, gift-card, and shipping-protection products are excluded from output. The full scrape completed, then the existing CSV and summary were postprocessed to apply the expanded out-of-scope exclusions and correct the `distinct_images` summary metric after a rerun attempt hit Wildfang rate limiting.

Size extraction uses Okendo variant labels first, then conservative ordered-size wording from review text. Measurement extraction is deterministic regex-only against review title, body, variant, and Okendo reviewer attributes.

The CSV and summary JSON were synced to `s3://fwm-scraping-data-briannasinger`.
