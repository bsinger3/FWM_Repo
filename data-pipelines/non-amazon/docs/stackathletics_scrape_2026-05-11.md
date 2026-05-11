# Stack Athletics Scrape - 2026-05-11

## Scope

- Merchant: `stackathletics.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_stackathletics_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/stackathletics_com/`
- Output CSV: `stackathletics_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `stackathletics_com_reviews_matching_amazon_schema_summary.json`

## Source And Coverage

Stack Athletics was selected as a first-time scrape after duplicate checks across scripts, docs, claim files, active claim files, and output folders.

Product discovery used the public Shopify catalog:

```text
https://stackathletics.com/products.json?limit=250&page=1
```

The catalog exposed 54 unique products. The scraper fetched each public product page, parsed the embedded Okendo product review JSON, and paged the public Okendo review endpoint until each product's review-media count was covered or no further page remained.

## Result

- Products discovered: 54
- Products scanned: 54
- Review pages scanned: 83
- Rows written: 27
- Distinct product URLs in rows: 9
- Rows with customer image: 27
- Rows with catalog model image: 0
- Rows with ordered size: 6
- Rows with measurements: 8
- Supabase-qualified rows: 3
- Coverage exhaustive: yes

The run completed without 429/captcha/WAF behavior after fixing an internal Okendo URL-join bug found during the smoke run.

## Notes

- Rows are customer review image rows from public Okendo data.
- The target `Courtside Dress` product had 8 review images and all 8 were captured.
- Size and measurement parsing is deterministic through the existing Step 1 intake parser; rows without explicit size or measurement text were retained in raw output.
