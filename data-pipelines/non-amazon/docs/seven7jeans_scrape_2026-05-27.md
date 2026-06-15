# Seven7 Jeans scrape notes - 2026-05-27

## Triage

- Retailer: `seven7jeans_com`
- Domain: `seven7jeans.com`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage status: `sovrn_first_pass_scrape_candidate`
- Pricing model: `CPA+CPC`
- Provider hint: `unknown`
- Reviews present: yes
- Photo review status: `unknown_sample_too_small`
- Shipping geos: `CA|US`
- Payout fields: not populated

## Outcome

Added a first-pass Seven7 Jeans adapter for the triage women’s Dress category using public category pages and public PDP HTML/Next.js flight payloads only.

The site is a Merchantly storefront. Product reviews are exposed inline in the public product payload as `productReviews`; the review component renders rating, title, body, color bought, size bought, height, nickname, location, and date. No public customer review image/media fields were found in the sampled implementation or final category scan, so the output uses `image_source_type=catalog_model_image` from public PDP product images with size/color variant context.

No 429, captcha, WAF, or auth behavior was encountered during the final run.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_seven7jeans_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\seven7jeans_com\seven7jeans_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\seven7jeans_com\seven7jeans_com_reviews_matching_intake_schema_summary.json`
- Completed claim: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\_claims\seven7jeans_com.txt`

## Metrics

- Category pages scanned: 1
- Category products discovered: 16
- Products scanned: 16
- Approved reviews seen in public payloads: 2
- Products with review media: 0
- Rows written: 60
- Rows with customer review image: 0
- Rows with catalog model image: 60
- Rows with size: 60
- Rows with color: 60
- Products with catalog fallback rows: 16
- Stop reason: `none`

## Revisit Notes

Recheck the Merchantly public product payload and review component before the next refresh. If `productReviews.reviews` begins exposing image/media fields, the adapter already checks common media keys and will emit `customer_review_image` rows before falling back to catalog images.
