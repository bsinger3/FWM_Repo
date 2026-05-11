# FashionPass Scrape Handoff - 2026-05-11

## Scope

- Merchant: `fashionpass_com`
- Triage rank: 68
- Triage URL: `https://www.fashionpass.com/product/ronny-kobo/verna-top`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_fashionpass_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/fashionpass_com/`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `fashionpass_com.claim` was present.
- No old `_claims/fashionpass_com.txt` history was present.
- No existing script, handoff doc, or local data output was present.
- Created active claims in both repo and data-root claim directories.

## Adapter And Coverage

- Adapter: `fashionpass_lead_neighborhood_review_api`
- Product discovery source: lead PDP `__NEXT_DATA__`, including the lead product, product pairings, and recent/related product data.
- Public review source: `https://reviews.fashionpass.com/api/v1/Review/GetReviews`
- Public image source: `https://fashionpass.s3-us-west-1.amazonaws.com/review_uploads_compressed/...`
- Products discovered: 20
- Products scanned: 20
- Products excluded from output: 5
- Review products scanned: 15
- Reviews seen: 1,332
- Customer-image reviews seen: 534
- Exhaustive review paging: false. The full site catalog endpoint advertises about 12,098 products, so the default run was fixed to avoid an over-broad full-site scrape. Full-catalog mode is available only with `--full-catalog`.
- Stop condition: completed bounded lead-neighborhood run.
- No 429, captcha, WAF, or block response was encountered.

## Notes

- The triage fast probe had `image_reviews_found_in_fast_probe=0`, but the public FashionPass review API exposes customer review photos plus structured fit profile fields.
- Review rows include `sizeworn`, height, weight, age, body type, bra size, review text, product URL, and customer image URL.
- A first attempted full-catalog run was stopped because it was too broad for a generic next scrape; the script now defaults to the lead-neighborhood mode and requires `--full-catalog` for the 12k-product catalog.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/fashionpass_com/fashionpass_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/fashionpass_com/fashionpass_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 534
- Distinct reviews: 534
- Distinct customer images: 534
- Distinct product URLs: 15
- Rows with product URL: 534
- Rows with customer image: 534
- Rows with ordered size: 534
- Rows with any measurement/profile text: 534
- Supabase-qualified rows: 534

## Validation

- `python3 -m py_compile data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_fashionpass_reviews.py` passed.
- CSV and summary metrics were cross-checked and matched.
- Numeric measurement fields had no malformed values in the generated CSV.
- Three sampled customer image URLs returned HTTP 200 JPEG responses.
- Three sampled product URLs returned HTTP 200 HTML responses.
