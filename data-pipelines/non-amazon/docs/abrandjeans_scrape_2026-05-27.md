# Abrand Jeans scrape notes - 2026-05-27

## Triage

- Retailer: `abrandjeans_com`
- Domain: `abrandjeans.com`
- Source: `data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv`
- Triage bucket: `sovrn_first_pass_scrape_candidate`
- Provider hint: Okendo
- Reviews/photo reviews present: yes
- Shipping geos: `US`
- Commission model: CPC
- CPC amount: not populated in triage

## Outcome

Completed a public, category-bounded Okendo scrape. The public Shopify-style `products.json` endpoint returned 404, so product discovery used the triage women's category page and its public product links. Product pages exposed the Okendo subscriber ID and Shopify product ID, and the public Okendo reviews API was available.

The run scanned all 69 product links found on `https://abrandjeans.com/collections/womens-clothing-new-arrivals`. Okendo review media was syndicated across related products, so final rows were globally deduped by review ID and image URL. Thumbnail crops and non-image video media were excluded from the final image intake CSV.

No 429, captcha, WAF, auth wall, or challenge behavior was encountered.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_abrandjeans_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\abrandjeans_com\abrandjeans_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\abrandjeans_com\abrandjeans_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Category product links found: 69
- Products scanned: 69
- Review pages scanned: 69
- Exhaustive review paging: true
- Rows written: 10
- Distinct reviews: 10
- Distinct images: 10
- Rows with distinct product URL: 2
- Rows with any measurement: 10
- Rows with customer image: 10
- Rows with customer ordered size: 10
- Supabase-qualified rows: 10

## Revisit Notes

This was complete for the triage women's new-arrivals category. A broader future scrape would need additional public category URLs from Abrand's women's navigation, still using only public PDPs and public Okendo review endpoints.
