# Liverpool Style Scrape - 2026-05-11

## Scope

- Site: `https://liverpoolstyle.com`
- Retailer key: `liverpoolstyle_com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_liverpoolstyle_reviews.py`
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/liverpoolstyle_com/liverpoolstyle_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/liverpoolstyle_com/liverpoolstyle_com_reviews_matching_amazon_schema_summary.json`

## Run

Command:

```bash
FWM_DATA_DIR=/Users/briannasinger/Projects/FWM_Data python3 data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_liverpoolstyle_reviews.py --request-delay-seconds 0.75
```

The scraper discovers the public Shopify catalog, batches public Klaviyo review counts, and scans product-level Klaviyo media pages for in-scope women's clothing products with public reviews. It stops on 429/captcha/WAF-like pressure signals.

## Coverage

- Products discovered: 665
- Products scanned: 665
- Products in current women's-clothing scope: 558
- Products excluded from output: 107
- Products with public reviews: 360
- Total public reviews reported by Klaviyo: 2,882
- Review pages scanned: 323
- Exhaustive review paging: yes, all public Klaviyo media pages exposed for scanned in-scope reviewed products were requested.
- Stop/block behavior: none observed.

## Results

- Rows written: 12
- Distinct product URLs in output: 6
- Rows with customer image: 12
- Rows with ordered size: 10
- Rows with deterministic measurements: 2
- Supabase-qualified rows: 2

The catalog grew from the prior 612-product run to 665 products. Public Klaviyo media remains sparse; the refreshed run preserved the same 12 deduped customer-image rows while updating catalog and review-count coverage.
