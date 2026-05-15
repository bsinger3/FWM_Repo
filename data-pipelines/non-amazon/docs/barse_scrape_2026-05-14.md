# Barse Scrape - 2026-05-14

## Scope

- Merchant: `barse.com`
- Triage rank: 31
- Triage bucket: `scrape now`
- Provider hint: Judge.me
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_barse_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/barse_com/`

## Source And Coverage

Older `_claims` notes already marked Barse as jewelry/out-of-scope on 2026-05-05. This run repeats and documents that finding with the current standardized output and summary files.

The scrape used only public sources:

- Shopify product catalog: `https://www.barse.com/products.json`
- Judge.me all-reviews endpoint: `https://api.judge.me/reviews/all_reviews_js_based`

The Shopify catalog completed without pressure signals and exposed 1,676 products. Product types were overwhelmingly jewelry: 1,665 products were earrings, necklaces, rings, or bracelets.

Judge.me text reviews were available, but the public media-specific probes did not expose customer review images:

- `sort_by=with_pictures`: 0 review blocks and 0 image links
- `sort_by=with_media`: 0 review blocks and 0 image links
- Recent review sample pages 1-3: 75 review blocks and 0 customer image links

No login, cookies, captcha bypass, WAF bypass, or aggressive retry behavior was used.

## Result

- Products discovered: 1,676
- Products scanned: 1,676
- Review sample pages scanned: 3
- Rows written: 0
- Distinct reviews: 0
- Distinct images: 0
- Rows with customer image: 0
- Rows with measurements: 0
- Supabase-qualified rows: 0
- Scope status: `completed_no_public_review_images_or_apparel_fit_signal`

## Revisit Notes

Skip Barse for the normal apparel fit-image queue unless a new public customer media feed or relevant apparel/model-measurement product source appears. The public catalog is jewelry-focused and does not provide useful body-fit measurement rows.
