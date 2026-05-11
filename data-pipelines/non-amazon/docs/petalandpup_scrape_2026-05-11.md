# Petal & Pup Scrape - 2026-05-11

## Scope

- Site: `https://petalandpup.com`
- Retailer key: `petalandpup_com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_petalandpup_reviews.py`
- Output CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/petalandpup_com/petalandpup_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/petalandpup_com/petalandpup_com_reviews_matching_amazon_schema_summary.json`

## Run

Commands:

```bash
FWM_DATA_DIR=/Users/briannasinger/Projects/FWM_Data python3 data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_petalandpup_reviews.py --resume-existing --catalog-start-page 28 --page-checkpoint --workers 1 --catalog-delay 2.0 --review-delay 0.5
FWM_DATA_DIR=/Users/briannasinger/Projects/FWM_Data python3 data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_petalandpup_reviews.py --resume-existing --catalog-start-page 29 --page-checkpoint --workers 1 --catalog-delay 2.0 --review-delay 0.5
```

The scraper was patched to run on macOS by using whichever public `curl` binary is available, read legacy BOM-prefixed summaries with `utf-8-sig`, and emit standard `matching_amazon_schema` files while preserving legacy intake filenames.

## Coverage

- Products discovered: 6,774
- Apparel products scanned: 5,669
- Products with review-image rows: 1,600
- Catalog delta: page 28 now contains 31 products, including 15 apparel products; page 29 is empty.
- Review pages scanned this run: 15 product review endpoints from the page-28 delta.
- Exhaustive review paging: yes for the page-28 delta; the existing full historical scrape had already completed pages 1-27.
- Stop/block behavior: none observed.

## Results

- Rows written: 16,945
- Distinct product URLs in output: 1,600
- Rows with customer image: 16,945
- Rows with ordered size: 11,697
- Rows with deterministic measurements: 11,643
- Supabase-qualified rows: 11,604

The page-28 delta produced 138 review-image rows before final merge, but all deduped against the existing full output. Final row and qualified-row counts therefore remain unchanged, while catalog coverage is updated through the current empty page 29 boundary.
