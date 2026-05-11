# Karen Millen scrape notes - 2026-05-11

## Triage

- Retailer: `karenmillen_com`
- Domain: `karenmillen.com`
- Triage rank: 53
- Triage bucket: `build adapter / API inspect`
- Provider hint: Bazaarvoice
- Fast-probe media hint: 3 review-image/media hints

## Outcome

Stopped at public preflight because the site returned AWS WAF challenge markers on normal HTML responses and did not expose usable public product feeds in the probed sources.

Public probes attempted:

- `https://www.karenmillen.com/`
- `https://www.karenmillen.com/us/categories/womens-dresses`
- `https://www.karenmillen.com/us/sitemap.xml`
- `https://www.karenmillen.com/products.json?limit=1`

The homepage and category page returned HTTP 200 HTML, but both included `edge.sdk.awswaf.com`, `challenge.js`, and `awswaf` markers. The sitemap and Shopify-style products probe returned rendered HTML 404 responses with the same WAF markers. Per scrape guardrails, no Bazaarvoice endpoint guessing or challenge workaround was attempted.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_karenmillen_reviews.py`
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/karenmillen_com/karenmillen_com_reviews_matching_amazon_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/karenmillen_com/karenmillen_com_reviews_matching_amazon_schema_summary.json`

## Metrics

- Products discovered: 0 usable product sources
- Products scanned: 0
- Products excluded from output: 0
- Review pages scanned: 0
- Exhaustive review paging: false
- Rows written: 0
- Distinct reviews: 0
- Distinct images: 0
- Rows with distinct product URL: 0
- Rows with any measurement: 0
- Rows with customer image: 0
- Rows with customer ordered size: 0
- Supabase-qualified rows: 0

## Revisit Notes

Revisit only if a documented public product feed and public Bazaarvoice review endpoint can be used without WAF/challenge handling. Do not retry with pressure, captcha solving, WAF bypass, or browser automation intended to defeat the challenge.
