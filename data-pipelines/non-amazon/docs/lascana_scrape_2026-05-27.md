# LASCANA scrape notes - 2026-05-27

## Triage

- Retailer: `lascana_com`
- Sovrn merchant domain: `lascana.at`
- Scrape target confirmed from triage evidence/public pages: `https://www.lascana.com`
- Source: `data-pipelines/docs/sovrn_commerce/sovrn_commerce_scrape_triage_candidates.csv`
- Triage bucket: `sovrn_first_pass_scrape_candidate`
- Provider: Yotpo
- Reviews/photo reviews present: yes
- Shipping geos: `DE|US`
- Commission model: CPC
- CPC amount: not populated in triage

## Outcome

Completed a public, category-bounded scrape from the triage category `https://www.lascana.com/Dresses`. The Sovrn merchant field is `lascana.at`, but the payout-prioritized row's category and sample PDP evidence all pointed at the US storefront on `www.lascana.com`, so that storefront was used.

The PDPs expose `PageLevelData`, the Yotpo app key, and the widget instance ID in public page source/scripts. Review media was collected through the public Yotpo widget API using selected color/size option SKUs such as `X29439-2-GYPR`. Some Yotpo review images appear under multiple color URLs for the same style, so final rows were deduped by review ID and image URL.

No 429, captcha, WAF, auth wall, or challenge behavior was encountered.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_lascana_reviews.py`
- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\lascana_com\lascana_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\lascana_com\lascana_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Category product links found: 30
- Products scanned: 30
- Review pages scanned: 37
- Exhaustive review paging: false
- Rows written: 11
- Distinct reviews: 11
- Distinct images: 11
- Distinct products: 6
- Rows with customer image: 11
- Rows with customer ordered size: 9
- Rows with any measurement: 4
- Supabase-qualified rows: 4

## Revisit Notes

This pass is bounded to the triage Dresses category and the first three Yotpo pages per product. A broader refresh can add more public category URLs from the same storefront and raise the page limit, keeping the same public PDP/Yotpo adapter and pressure-stop behavior.
