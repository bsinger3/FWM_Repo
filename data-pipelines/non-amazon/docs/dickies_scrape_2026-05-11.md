# Dickies Scrape - 2026-05-11

## Result

Built a first-time public scraper for Dickies using Shopify catalog discovery and Yotpo customer review JSON. The scraper does not crawl product-page HTML because Dickies robots.txt disallows `/products/`; product URLs are derived from the public Shopify catalog/sitemap, and reviews are fetched from public Yotpo widget JSON by Shopify product ID.

The full run completed without 429, captcha, WAF, auth wall, or challenge markers.

## Outputs

- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_dickies_reviews.py`
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/dickies_com/dickies_com_reviews_matching_amazon_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/dickies_com/dickies_com_reviews_matching_amazon_schema_summary.json`
- Checkpoints:
  - `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/dickies_com/dickies_com_rows_checkpoint.jsonl`
  - `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/dickies_com/dickies_com_product_summaries_checkpoint.jsonl`

## Coverage

- Products discovered: 3,293
- Products scanned/classified: 3,293
- Products excluded from output: 2,274
- Review products scanned: 1,019
- Review pages scanned: 2,500
- Exhaustive review paging: yes
- Product review count hint across scanned Yotpo products: 160,831
- Rows filtered after audit as out-of-scope: 80 men-shorts rows

Discovery sources:

- Public Shopify `products.json`: 3,293 products across 14 pages.
- Public Shopify product sitemaps: reconciled with `products.json`.

## Qualification Metrics

- Rows written: 135
- Distinct reviews: 16
- Distinct images: 32
- Rows with customer image: 135
- Rows with distinct product URL: 38
- Rows with customer ordered size: 61
- Rows with any deterministic measurement: 76
- Supabase-qualified rows: 52

## Notes

The Yotpo data repeats the same review-image histories across some product/color URLs. The output intentionally keeps one row per review image per product URL after deduping stable row keys, because each row still has a distinct product-page candidate.

The final audit removed a neutral-titled shorts product categorized as `men-shorts-work` even though it carried a women-related feed signal. The current scraper treats product type as higher authority than broad catalog tags.
