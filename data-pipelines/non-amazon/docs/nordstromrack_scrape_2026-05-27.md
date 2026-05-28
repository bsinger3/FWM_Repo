# Nordstrom Rack scrape notes - 2026-05-27

## Scope

- Retailer: `nordstromrack_com`
- Domain: `nordstromrack.com`
- Source: approved category-specific Sovrn scrape from the updated non-Amazon triage plan.
- Intended coverage: women's clothing section only, not a whole-site scrape.
- Triage sample PDP: `https://www.nordstromrack.com/s/calvin-klein-scuba-crepe-fit-flare-dress/7881634?origin=category-personalizedsort&breadcrumb=Home%2FWomen%2FClothing%2FDresses&color=419`
- Triage category seed: `https://www.nordstromrack.com/shop/trend/women/bold-colors`

## Outcome

Stopped at public preflight because the sample PDP returned WAF/challenge behavior instead of normal product HTML or app data.

Observed response:

- HTTP status: `200`
- Content type: `text/html; charset=UTF-8`
- Challenge markers: `istl-response`, `istlWasHere`
- Title: empty
- Normal app/product data found: no

Per scrape guardrails, no product discovery, review endpoint probing, browser challenge handling, authentication, captcha/WAF bypass, or retry pressure was attempted after this signal.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_nordstromrack_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\nordstromrack_com\nordstromrack_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\nordstromrack_com\nordstromrack_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Products discovered: 0
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

Revisit only if a normal public product/category or review endpoint is documented without challenge handling. Keep the scope category-specific to women's clothing, and continue to stop immediately on 429, captcha, WAF, auth, DataDome, or similar challenge behavior.
