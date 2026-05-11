# Macy's Scrape Handoff - 2026-05-11

## Scope

- Merchant: `macys_com`
- Triage rank: 64
- Triage URL: `https://www.macys.com/shop/product/tommy-hilfiger-womens-keyhole-neck-sheath-dress?ID=16994518`
- Provider hint: Bazaarvoice
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/macys_com/`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `macys_com.claim` was present.
- No old `_claims/macys_com.txt` history was present.
- No existing script, handoff doc, or local data output was present.
- Created active claims in both repo and data-root claim directories.

## Probe Result

- First public PDP request returned HTTP 403 with an `Access Denied` page.
- Stopped immediately per the scrape guardrail.
- No retries, bypass attempts, browser challenge handling, S3 sync, or alternate endpoint probing were performed.
- Because the block happened on the initial public page request, no product discovery or review paging was attempted.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/macys_com/macys_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/macys_com/macys_com_reviews_matching_amazon_schema_summary.json`

## Qualification Metrics

- Rows written: 0
- Distinct reviews: 0
- Distinct customer images: 0
- Distinct product URLs: 0
- Rows with product URL: 0
- Rows with customer image: 0
- Rows with ordered size: 0
- Rows with any measurement/profile text: 0
- Supabase-qualified rows: 0

## Recommendation

Do not retry Macy's in the current scrape queue without explicit user approval and a revised access plan. The current public probe hits access denial before review-provider inspection.
