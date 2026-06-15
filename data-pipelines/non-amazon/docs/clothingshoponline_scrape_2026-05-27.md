# Clothing Shop Online scrape notes - 2026-05-27

## Triage

- Retailer: `clothingshoponline_com`
- Domain: `clothingshoponline.com`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage status: `sovrn_first_pass_scrape_candidate`
- Provider hint: `Yotpo; Loox`
- Reviews present: yes
- Photo review status: `unknown_sample_too_small`
- Shipping geos: `US`
- Estimated commission/click: `$0.14`

## Outcome

Added a first-pass Clothing Shop Online adapter using public collection pages, public Hydrogen PDP HTML, and public Yotpo `api-cdn` review JSON only.

Customer review media exists but is sparse, so the scraper emits `customer_review_image` rows where Yotpo review images are available and falls back to `catalog_model_image` rows for apparel PDPs with useful public catalog/model/variant images and size/color data. Accessory-only items in the women category were skipped when they had no useful apparel context.

No 429, captcha, WAF, or auth behavior was encountered during the final run.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_clothingshoponline_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\clothingshoponline_com\clothingshoponline_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\clothingshoponline_com\clothingshoponline_com_reviews_matching_intake_schema_summary.json`
- Completed claim: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_claims\clothingshoponline_com.txt`

## Metrics

- Collection pages scanned: 39
- Products discovered: 619
- Products scanned: 619
- Review pages scanned: 621
- Reviews seen: 1,647
- Rows written: 1,791
- Rows with customer review image: 72
- Rows with catalog model image: 1,719
- Rows with size: 1,723
- Rows with color: 1,791
- Products with customer review images: 29
- Products with catalog fallback rows: 578
- Stop reason: `none`

## Revisit Notes

The adapter depends on the public Yotpo loader app key in the site bundle and public Hydrogen PDP route payloads. Recheck the loader key, collection pagination, and Yotpo `api-cdn` response shape before the next refresh.
