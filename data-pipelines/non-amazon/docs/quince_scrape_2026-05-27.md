# Quince scrape refresh notes - 2026-05-27

## Triage

- Retailer: `quince_com`
- Domain: `quince.com`
- Source: `data-pipelines/non-amazon/docs/sovrn_commerce_scrape_triage_candidates.csv`
- Triage status: approved refresh of existing scraper
- Provider hint: Yotpo
- Picture reviews present: yes
- Shipping geos: `US`
- Estimated commission/click: `$0.07`

## Outcome

Refreshed the existing Quince adapter against public Quince pages/endpoints only.

Patch notes:

- Updated discovery for the current public sitemap index: `sitemap_us.xml` now points to `sitemap_pdps.xml`.
- Replaced the stale hardcoded Next.js build ID with public PDP build ID discovery.
- Added hard-stop checks for 401/403/429/WAF/captcha/auth challenge markers.
- Preserved Quince API pagination behavior where a non-auth HTTP 400 after collected pages is treated as pagination exhaustion, not a WAF stop.

No 429, captcha, WAF, or auth behavior was encountered during the final run.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_quince_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\quince_com\quince_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\quince_com\quince_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Candidate URLs discovered: 2,573
- Products scanned: 2,573
- Rows written: 48,085
- Distinct reviews: 43,357
- Distinct images: 43,343
- Distinct products: 771
- Rows with customer review image: 48,085
- Rows with customer ordered size: 34,689
- Rows with any measurement: 8,538
- Supabase-qualified rows: 6,876
- Errors: 0

## Revisit Notes

This adapter depends on Quince's public Next.js product data route plus the public `api.onequince.com/review-system/reviews/external/fetch-reviews` media-review endpoint. Recheck sitemap structure and public build ID discovery before the next refresh.
