# Rolla's Jeans scrape - 2026-05-27

## Scope

- Retailer: `rollasjeans_com`
- Source triage row: `data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv`
- Triage notes: first-pass Sovrn candidate, CPC, reviews present, photo reviews present, shipping `US`, provider unknown, CPC amount not populated.
- Seed category: `https://rollasjeans.com/collections/womens/clothing/tops`
- Seed PDPs:
  - `https://rollasjeans.com/products/petal-bloom-blouse`
  - `https://rollasjeans.com/products/script-ringer-tee`
  - `https://rollasjeans.com/products/classic-ringer-tee-petite-logo-cream`

## Adapter

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_rollasjeans_reviews.py`
- Public surfaces used:
  - category and PDP HTML
  - embedded public Next.js `__NEXT_DATA__` JSON
  - Shopify CDN catalog/model images referenced by public PDP data
- Stop policy: stop on 429/captcha/WAF/auth behavior.

## Review/provider findings

The public product pages did not expose a named review provider or public customer-review media payload during inspection. No Okendo, Judge.me, Loox, Stamped, Yotpo, Bazaarvoice, or PowerReviews markers were found in the bounded category/PDP HTML inspected by the scraper.

Because the user allowed a fallback where customer photos are sparse/unavailable, this scrape emits `image_source_type=catalog_model_image` rows. Each row uses public catalog/model images plus model fit details from PDP JSON, including model name, height, and apparel size where available.

## Output

- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\rollasjeans_com\rollasjeans_com_reviews_matching_intake_schema.csv`
- Summary JSON: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\rollasjeans_com\rollasjeans_com_reviews_matching_intake_schema_summary.json`

Final run:

- Category product links found: 46
- Products scanned: 47, including the sample PDP not present in the category list
- Rows written: 94
- Distinct products: 47
- Distinct images: 94
- Customer review image rows: 0
- Catalog model image rows: 94
- Rows with image, product URL, size, and measurement: 86
- Blocked/challenged: no
- Stop reason: `completed_public_catalog_model_fallback_scan`

## Limits

- This is not a whole-site scrape; it is bounded to the women's tops category and supplied sample PDP evidence.
- No private, authenticated, or reverse-engineered endpoints were used.
- Rows are catalog/model fallback rows, not customer review-photo rows, because no usable public customer-review media source was found.
