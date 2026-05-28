# SPANX Scrape - 2026-05-27

Source: payout-prioritized Sovrn triage candidate from `sovrn_commerce_scrape_triage_candidates.csv`.

- Merchant: `spanx_com`
- Triage facts: first-pass candidate, Yotpo, `photo_reviews=yes`, shipping `CA|GB|US`, estimated commission/click `$0.14`.
- Sample source URLs:
  - `https://spanx.com/collections/jeans`
  - `https://spanx.com/products/spanxshape-authentic-360-wide-leg-jeans?v=48685075071187&bau-context=standard&Color=Vintage+Coastline`
  - `https://spanx.com/products/spanxshape-authentic-360-90s-straight-leg-jeans?v=48685070614739&bau-context=standard&Color=Alabaster`
  - `https://spanx.com/products/spanxsupersmooth-authentic-360-lightweight-utility-barrel-leg-jeans?v=48685281738963&bau-context=standard&Color=Oceanic`

## Pre-Scrape Checks

- Checked repo scripts/docs and data-root `_active_scrape_claims`, `_claims`, and output directories for `spanx` / `spanx_com`.
- No prior SPANX scrape script, output directory, active claim, completed claim, or scrape doc was found.
- Added active claim at `FWM_Data/non-amazon/data/step_1_raw_scraping_data/_active_scrape_claims/spanx_com.claim` before scraping.

## Public Sources Used

- Public sitemap index: `https://spanx.com/sitemap.xml`
- Public product sitemap: `https://spanx.com/sitemap/products/1.xml`
- Public product pages for Shopify product IDs and product metadata.
- Public Yotpo product widget JSON via key exposed on SPANX product pages: `PRZxHghLYKMWCTmuTuGTzVGDbnWOdoHYjOpVCQiL`.

The scrape used public pages/endpoints only. No auth, captcha, WAF bypass, or non-public endpoint was used.

## Output

- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_spanx_reviews.py`
- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/spanx_com/spanx_com_reviews_matching_intake_schema.csv`
- Summary: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/spanx_com/spanx_com_reviews_matching_intake_schema_summary.json`

## Results

- Products discovered: 395 from the public product sitemap.
- Products scanned: 395.
- Products excluded from output: 7 tights / hosiery-like products.
- Review pages scanned: 1,035.
- Exhaustive review paging: yes.
- Rows written: 3,763 customer review image rows.
- Distinct product URLs with rows: 150.
- Rows with customer image: 3,763.
- Rows with ordered size: 2,488.
- Rows with at least one measurement: 2,567.
- Supabase-qualified rows: 2,371.
- Errors: none.

Validation notes:

- CSV row count matches `rows_written` in the summary.
- Sampled customer image URL returned HTTP 200 with `image/jpeg`.
- Sampled SPANX product URL returned HTTP 200 with `text/html`.
- Normalized numeric measurement fields in the summary validator reported zero invalid values.
