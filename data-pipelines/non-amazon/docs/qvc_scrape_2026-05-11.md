# QVC Scrape Handoff - 2026-05-11

## Scope

- Merchant: `qvc_com`
- Triage rank: 65
- Triage URL: `https://www.qvc.com/tommie-copper-4pk-ultrablend-ankle-compression-socks.product.V85667.html`
- Provider hint: Bazaarvoice
- Data root: `/Users/briannasinger/Projects/FWM_Data`

## Coordination

- Checked `_active_scrape_claims` before starting.
- No active `qvc_com.claim` was present.
- No old `_claims/qvc_com.txt` history was present.
- No existing script, handoff doc, or local data output was present.
- Created active claims in both repo and data-root claim directories.

## Probe Result

- Lead PDP returned HTTP 200.
- The page exposes Bazaarvoice deployment `QVC/main_site/production/en_US`, display code `1689-en_us`, and passkey `6x3l6m5z3ojhr44ie8n2lmfqu`.
- Bazaarvoice reviews API returned review data for product `V85667`.
- The lead product is compression socks, outside the current women's-clothing publish scope.
- Sampled 8 public reviews from the lead product; none had `Photos`, ordered size, or measurement/profile context.

## Output

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/qvc_com/qvc_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/qvc_com/qvc_com_reviews_matching_amazon_schema_summary.json`

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

Skip this triage lead for now. A QVC scrape would need a different in-scope women's-clothing seed URL and evidence of customer review photo attachments before implementation.
