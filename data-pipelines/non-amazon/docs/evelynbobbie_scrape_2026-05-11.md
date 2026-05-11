# Evelyn Bobbie Scrape - 2026-05-11

## Scope

- Site: `https://evelynbobbie.com`
- Retailer key: `evelynbobbie_com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_evelynbobbie_reviews.py`
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/evelynbobbie_com/evelynbobbie_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/evelynbobbie_com/evelynbobbie_com_reviews_matching_amazon_schema_summary.json`

## Run

Command:

```bash
FWM_DATA_DIR=/Users/briannasinger/Projects/FWM_Data python3 data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_evelynbobbie_reviews.py --request-delay-seconds 0.02
```

The scraper uses public Shopify catalog/sitemap discovery plus the lead URL, then scans public Yotpo product review endpoints and the public Yotpo v3 store review feed. It now stops immediately on `429`, captcha, or WAF-like responses instead of retrying through them.

Adapter: `shopify_catalog_plus_yotpo_product_level_and_v3_store_feed`.

## Coverage

- Products discovered: 27
- Products scanned: 27
- Products excluded from output: 3 (`digital-gift-card`, `travel-bag`, `wash-bag`)
- Product sources: 27 from Shopify `products.json`, 27 from product sitemap, 1 lead URL; all sitemap/lead URLs duplicated Shopify handles.
- Review pages scanned: 1,174 total: 901 product-level Yotpo pages and 273 Yotpo v3 store-feed pages.
- Store-feed reviews observed: 27,300
- Store-feed media reviews observed: 2
- Product review-count hint: 88,509
- Exhaustive review paging: yes, all public Yotpo pages exposed by the scanned product endpoints and store-feed pagination were requested.
- Products with customer-image rows before final dedupe: 3
- Deduped products with output rows: 2
- Stop/block behavior: none observed.

## Results

- Rows written: 2
- Distinct product URLs in output: 2
- Rows with customer image: 2
- Rows with ordered size: 1
- Rows with deterministic measurements: 1
- Supabase-qualified rows: 1

The visible review-count signal is real, but public customer review media is very sparse. The Yotpo v3 store feed required `perPage=100` rather than `per_page=100`; after correcting that, the full public feed still exposed only 2 customer-image reviews. The triage probe's high media hint appears to be catalog/page image markup rather than public review media.
