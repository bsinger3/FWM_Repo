# Anne Cole scrape 2026-05-11

## Result

- Site: `annecole.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_annecole_reviews.py`
- Adapter: public Okendo product-level review API
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/annecole_com/annecole_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/annecole_com/annecole_com_reviews_matching_amazon_schema_summary.json`

The scraper was refreshed from the older `matching_intake_schema` output names to the current `matching_amazon_schema` names and now writes `image_source_type=customer_review_image` / `image_source_detail=okendo_review_media`.

## Coverage

- Products discovered: 671
- Products scanned: 671
- Products excluded from output: 3 accessories
- Review pages scanned: 1,035
- Exhaustive review paging: `true`
- Product review count hint: 62,522
- 429/captcha/WAF encountered: no

Product discovery reconciles Shopify `products.json` and the public product sitemap. Each product with a Shopify ID is paged through the public Okendo product review endpoint.

## Qualification Metrics

- Rows written: 36
- Distinct reviews: 30
- Distinct images: 36
- Distinct product URLs: 18
- Rows with customer image: 36
- Rows with ordered size: 25
- Rows with any measurement: 10
- Supabase-qualified rows: 8
- Invalid normalized numeric fields: 0

Validation checks found no blank image URLs, no blank product URLs, no homepage/root product URLs, and no missing `customer_review_image` source markers.
