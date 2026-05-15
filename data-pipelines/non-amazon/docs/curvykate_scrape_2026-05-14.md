# Curvy Kate Scrape - 2026-05-14

## Scope

- Merchant: `curvykate.com`
- Triage rank: 82
- Triage bucket: `manual inspect`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_curvykate_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/curvykate_com/`

## Source And Coverage

This was a full public catalog product-page scrape, not a sheet-URL-only scrape.

Sources used:

- Public Shopify catalog: `https://www.curvykate.com/products.json`
- Every public product page discovered from that catalog
- Public Feefo product review API keyed by the `data-parent-product-sku` found on product pages

Coverage:

- Products discovered: 278
- Product pages scanned: 278
- Feefo parent SKUs scanned: 173
- Feefo review pages scanned: 174
- Full catalog complete: yes
- Errors: none

The scraper stops on 429/captcha/WAF-like responses and uses only public endpoints. One transient read timeout happened during the first full run attempt; retry handling was added, and the completed rerun finished without errors.

## Result

- Rows written: 33,446
- Distinct Feefo review IDs: 1,676
- Distinct product image URLs: 1,459
- Distinct product URLs in output rows: 397
- Rows with comments: 33,446
- Rows with image URL: 33,446
- Rows with any parsed measurement: 2,215
- Rows with customer review image: 0
- Rows with catalog model image: 0
- Rows with catalog product image: 33,446
- Supabase customer-image qualified rows: 0

## Notes

- Feefo reviews are public and text-rich but do not expose customer review image URLs.
- The Feefo media-gallery endpoint was also checked across all 173 parent SKUs and returned no public customer media.
- Rows use `image_source_type=catalog_product_image` because images are public Shopify product-gallery images joined to Feefo review text. These rows are deliberately not labeled as customer review images.
- Some Feefo parent SKUs group multiple color/product pages together, so output rows can reference Feefo product URLs beyond the 278 exact scanned page URLs while still being sourced from the full scanned catalog.
