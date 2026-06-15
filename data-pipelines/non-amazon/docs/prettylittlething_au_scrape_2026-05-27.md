# PrettyLittleThing AU scrape notes - 2026-05-27

## Triage

- Retailer: `prettylittlething_com_au`
- Domain: `prettylittlething.com.au`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage bucket: `sovrn_first_pass_scrape_candidate`
- Provider hint: Bazaarvoice
- Photo reviews present: yes
- Shipping geos: `AU|CA|FR|GB|IE|US`
- Estimated commission/click: `$0.04`

## Outcome

Stopped at public preflight. The sample AU category page and all three sample AU PDPs returned HTTP 200 HTML, but each response included AWS WAF challenge markers: `edge.sdk.awswaf.com`, `challenge.js`, and `awswaf`.

Public probes attempted:

- `https://www.prettylittlething.com.au/categories/womens-tops-shirts`
- `https://www.prettylittlething.com.au/product/cotton-oversized-cuff-shirt_plt01115?colour=tan`
- `https://www.prettylittlething.com.au/product/striped-oversized-lightweight-shirt_plt12337?colour=blue`
- `https://www.prettylittlething.com.au/product/plt-label-oversized-collar-button-down-fitted-shirt_plt00599?colour=blue`

Per scrape guardrails, no Bazaarvoice endpoint probing, browser challenge handling, captcha handling, WAF workaround, auth flow, or pressure retry was attempted.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_prettylittlething_au_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\prettylittlething_com_au\prettylittlething_com_au_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\prettylittlething_com_au\prettylittlething_com_au_reviews_matching_intake_schema_summary.json`

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
