# Premcurve scrape - 2026-05-05

## Output

- Retailer: `premcurve_com`
- Output CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/premcurve_com/premcurve_com_reviews_matching_intake_schema.csv`
- Summary JSON: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/premcurve_com/premcurve_com_reviews_matching_intake_schema_summary.json`

## Result

- Public Shopify product URLs discovered: 1,689
- Rows scraped: 1,054
- Distinct review IDs: 355
- Distinct image URLs: 1,054
- Distinct product URLs: 103
- Rows with image and product URL: 1,054
- Rows with user comment: 1,054
- Rows with size display: 124
- Rows with any measurement: 130
- Rows with image, product, size, and measurement: 68

## Notes

The original Premcurve output was a seed-only scrape with 6 rows from 1 product. The 2026-05-05 refresh discovered the public Shopify catalog and used the public Judge.me media review feed plus the seed product widget.

Diagnostics showed that exhaustive per-product provider fallback repeatedly returned the same Judge.me aggregate rows and then spent substantial time on zero-row probes. The final output therefore records the discovered catalog size and retains the public aggregate media rows with populated product URLs.
