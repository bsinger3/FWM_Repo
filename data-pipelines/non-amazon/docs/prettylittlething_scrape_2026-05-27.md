# PrettyLittleThing scrape notes - 2026-05-27

## Triage

- Retailer: `prettylittlething_com`
- Domains: `prettylittlething.com`, `ie.prettylittlething.com`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage bucket: `sovrn_first_pass_scrape_candidate`
- Provider hint: Bazaarvoice
- Photo reviews present: yes
- Shipping geos: `AU|CA|FR|GB|IE|US`
- Estimated commission/click: `$0.39`

## Outcome

Stopped at public preflight. The sample category page and all sample PDPs returned HTTP 200 HTML, but each response included AWS WAF challenge markers: `edge.sdk.awswaf.com`, `challenge.js`, and `awswaf`.

Public probes attempted:

- `https://www.prettylittlething.com/categories/womens-swimwear-bikinis-bikini-tops`
- `https://www.prettylittlething.com/product/print-basic-triangle-bikini-top_plt02217?colour=black`
- `https://www.prettylittlething.com/product/u-bar-underwired-bikini-top_plt05926?colour=burgundy`
- `https://www.prettylittlething.com/product/print-basic-triangle-bikini-top_plt02217?colour=pink`
- `https://www.prettylittlething.ie/product/print-basic-triangle-bikini-top_plt02217?colour=black`

Per scrape guardrails, no Bazaarvoice endpoint probing, browser challenge handling, captcha handling, WAF workaround, auth flow, or pressure retry was attempted.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_prettylittlething_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\prettylittlething_com\prettylittlething_com_reviews_matching_amazon_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\prettylittlething_com\prettylittlething_com_reviews_matching_amazon_schema_summary.json`

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
