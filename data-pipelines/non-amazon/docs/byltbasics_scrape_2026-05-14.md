# BYLT Basics Scrape - 2026-05-14

## Scope

- Merchant: `byltbasics.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_byltbasics_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/byltbasics_com/`

## Source And Coverage

This was a full public sitemap product-page scrape, not a sheet-URL-only scrape.

Sources used:

- Public sitemap index: `https://byltbasics.com/sitemap.xml`
- Every public product page discovered from product sitemaps
- Public Okendo product review API keyed by product-page Okendo/Shopify IDs

Coverage:

- Products discovered: 666
- Product pages scanned: 666
- Okendo review pages scanned: 1,416
- Full catalog complete: yes
- Errors: none

## Result

- Rows written: 48,736
- Distinct review IDs: 32,137
- Distinct image URLs: 1,784
- Distinct product URLs in output rows: 528
- Rows with ordered size: 9,045
- Rows with any parsed measurement: 10,248
- Rows with customer review image: 0
- Rows with catalog product image: 48,736
- Supabase customer-image qualified rows: 0

## Notes

- Okendo reviews expose review text, ordered size, reviewer height/usual-size attributes on many rows, and product/variant image URLs.
- The public Okendo payloads did not expose customer review media, so rows use `image_source_type=catalog_product_image`.
- Bundle and last-call products share grouped Okendo review pools; final output is deduped by review/product/image key.
