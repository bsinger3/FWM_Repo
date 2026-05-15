# Unbound Merino Scrape - 2026-05-14

## Scope

- Merchant: `unboundmerino.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_unboundmerino_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/unboundmerino_com/`

## Source And Coverage

This was a full public catalog product-page scrape, not a sheet-URL-only scrape.

Sources used:

- Public Shopify catalog: `https://unboundmerino.com/products.json`
- Every public product page discovered from that catalog
- Embedded public Okendo review metafields on product pages
- Public Okendo review pagination API from each product's `reviewsNextUrl`

Coverage:

- Products discovered: 152
- Product pages scanned: 152
- Okendo review pages scanned: 509
- Full catalog complete: yes
- Errors: none

## Result

- Rows written: 1,412
- Distinct review IDs: 1,126
- Distinct image URLs: 378
- Distinct product URLs in output rows: 145
- Rows with any parsed measurement: 145
- Rows with ordered size: 1,296
- Rows with customer review image: 0
- Rows with catalog product image: 1,412
- Supabase customer-image qualified rows: 0

## Notes

- Okendo reviews expose review text, ordered size, and product/variant image URLs.
- The public Okendo payloads did not expose customer review media, so rows use `image_source_type=catalog_product_image`.
- The scraper scanned all product pages even when a product had no output rows.
