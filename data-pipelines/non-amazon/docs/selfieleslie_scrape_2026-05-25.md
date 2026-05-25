# Selfie Leslie Scrape 2026-05-25

## Result

- Status: completed first-time public scrape
- Site: `https://www.selfieleslie.com`
- Adapter: Shopify catalog/sitemap discovery plus public Yotpo aggregate review API
- Output CSV: `/Users/briannasinger/Projects/FWM/FWM_Data/non-amazon/data/step_1_raw_scraping_data/selfieleslie_com/selfieleslie_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM/FWM_Data/non-amazon/data/step_1_raw_scraping_data/selfieleslie_com/selfieleslie_com_reviews_matching_intake_schema_summary.json`
- Scraper: `/Users/briannasinger/Projects/FWM/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_selfieleslie_reviews.py`

## Counts

- Products discovered/scanned: 19,212
- Products excluded from output scope: 13,179
- Yotpo review pages scanned: 175 of 175
- Reviews reported by Yotpo: 17,467
- Rows written: 655
- Distinct reviews: 496
- Distinct images: 655
- Distinct product URLs represented: 297
- Rows with any measurement: 451
- Rows with customer image: 655
- Rows with ordered size: 135
- Supabase-qualified rows: 124

## Notes

- Public Shopify `products.json` loaded through page 60, then returned a 403 boundary at page 61. The scraper records that boundary and continues with sitemap discovery plus Yotpo review paging.
- Yotpo `sort=images` returned media rows through page 28. Pages 29 through 175 were scanned and returned zero retained customer-image rows.
- Rows use public Yotpo review images and deterministic Yotpo custom fields for `Size`, `Height`, and `Weight` when present.
