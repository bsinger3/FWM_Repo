# Amalli Talli Scrape Notes - 2026-06-09

## Scope

- Retailer: `amallitalli_com`
- Domain: `amallitalli.com`
- Gap target: tall women, height 6ft+, long inseams
- Source queue: `outputs/measurement_coverage/20260609_human_labeled_approved_only/net_new_site_research_candidates.csv`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_amallitalli_reviews.py`
- Provider: Loox

## Outcome

Completed a public Loox photo-review scrape. Public `products.json` was available and used for product title-to-URL context. The public Loox widget endpoint was available with app ID `dhtRTz2ihe`; paging stopped after page 5 returned no photo rows.

No 429, captcha, WAF, auth wall, or challenge behavior was encountered.

## Outputs

- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/amallitalli_com/amallitalli_com_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/amallitalli_com/amallitalli_com_reviews_matching_intake_schema_summary.json`

## Metrics

- Products discovered from `products.json`: 200
- Loox review pages scanned: 5
- Rows written: 80
- Distinct reviews: 80
- Distinct images: 80
- Distinct product URLs: 44
- Rows with any measurement: 16
- Rows with image, product URL, and measurement: 16
- Rows with customer ordered size: 9
- Supabase-qualified rows: 8

## Notes

This is a good net-new source for tall coverage. The strongest rows include explicit height and sometimes inseam/weight, for example 6ft, 6ft1, 34-inch inseam, 36-inch inseam, and tall-pant fit context.
