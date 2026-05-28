# White House Black Market scrape notes - 2026-05-11

## Triage

- Retailer: `whitehouseblackmarket_com`
- Domain: `whitehouseblackmarket.com`
- Triage rank: 59
- Triage bucket: `build adapter / API inspect`
- Provider hint: Bazaarvoice
- Fast-probe signal: no review-media hint, comment-only measurements

## Outcome

Built a full public Bazaarvoice scraper for White House Black Market. The product sitemap exposed 3,951 product URLs, and the Bazaarvoice deployment exposed public BFD review JSON for product photo reviews. The scraper captured one row per Bazaarvoice review photo, preserving product URL, review text, reviewer nickname, ordered size when present, and deterministic height/weight range fields from Bazaarvoice context data.

Access stayed within public sitemap/product/review resources. No authentication, browser automation, captcha handling, WAF bypass, S3 sync, or private endpoint use was attempted. The run completed without 429, captcha, WAF, or challenge markers.

## Outputs

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_whitehouseblackmarket_reviews.py`
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/whitehouseblackmarket_com/whitehouseblackmarket_com_reviews_matching_amazon_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/whitehouseblackmarket_com/whitehouseblackmarket_com_reviews_matching_amazon_schema_summary.json`

## Metrics

- Products discovered: 3,951
- Products scanned: 3,951
- Products excluded from output: 3,143
- Review pages scanned: 3,951
- Exhaustive review paging: true
- Rows written: 2,433
- Distinct reviews: 973
- Distinct images: 1,438
- Rows with distinct product URL: 808
- Rows with any measurement: 1,658
- Rows with customer image: 2,433
- Rows with catalog model image: 0
- Rows with customer ordered size: 1,266
- Supabase-qualified rows: 1,201
- Coverage exhaustive: true
- Errors: none

## Qualification

This is a high-value scrape. The 1,201 Supabase-qualified rows have customer review images, product URLs, deterministic ordered sizes, and at least one deterministic height/weight range field on the same row. Additional rows preserve review text and images for later standardization even when size or measurement context is missing.

## Refresh - 2026-05-27

Refreshed `whitehouseblackmarket_com` as an approved Sovrn existing-scraper refresh. The Sovrn candidate row notes picture reviews present, Bazaarvoice, CPA+CPC, and estimated commission/click `$0.07`.

Adapter changes:

- Removed the forced `curl --http2` flag from Bazaarvoice requests because it exits with code 2 in the current Windows runtime.
- Added explicit UTF-8 decoding for `curl` subprocess output so Bazaarvoice review text with smart punctuation does not become `charmap` decode errors.
- Added repeatable `--product-url` for targeted PDP smoke checks against plan/sample URLs.
- Treat subprocess failures as stop conditions instead of silently producing a misleading zero-row refresh, and mark coverage non-exhaustive when product-level errors remain.

Refresh access stayed within public pages/endpoints: public WHBM product sitemap, public WHBM PDPs for inspection, and public Bazaarvoice BFD review JSON. No authentication, browser bypass, captcha handling, WAF bypass, S3 sync, or private endpoint use was attempted. The final run completed without 429, captcha, WAF, auth-wall, or challenge-marker behavior.

Refreshed outputs:

- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\whitehouseblackmarket_com\whitehouseblackmarket_com_reviews_matching_amazon_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\non-amazon\data\step_1_raw_scraping_data\whitehouseblackmarket_com\whitehouseblackmarket_com_reviews_matching_amazon_schema_summary.json`

Refresh metrics:

- Products discovered: 3,603
- Products scanned: 3,603
- Products excluded from output: 2,861
- Review pages scanned: 3,603
- Exhaustive review paging: true
- Rows written: 2,205
- Distinct reviews: 863
- Distinct images: 1,283
- Rows with distinct product URL: 742
- Rows with any measurement: 1,555
- Rows with customer image: 2,205
- Rows with catalog model image: 0
- Rows with customer ordered size: 1,175
- Supabase-qualified rows: 1,116
- Coverage exhaustive: true
- Errors: none

Compared with the 2026-05-11 run, current sitemap coverage is smaller (3,603 products vs. 3,951), and output is slightly smaller (2,205 rows vs. 2,433; 1,116 qualified rows vs. 1,201). The adapter still captures one row per public Bazaarvoice customer review photo and preserves size/height/weight context when present.
