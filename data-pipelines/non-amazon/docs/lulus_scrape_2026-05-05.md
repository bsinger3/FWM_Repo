# Lulus Scrape Notes - 2026-05-05

## Outcome

- Retailer: `lulus_com`
- Site: `https://www.lulus.com/`
- Output CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus_com/lulus_com_reviews_matching_intake_schema.csv`
- Summary JSON: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus_com/lulus_com_scrape_summary.json`
- Rows: 4,117 review image rows
- Distinct product URLs with rows: 22
- Rows with size: 4,117
- Rows with body measurements/profile stats: 2,322

## Method

Lulus does not expose a Shopify `products.json` catalog. Product discovery used the existing March 2026 workbook:

`FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus/Lulus_ProdLinks_March2026.xlsx`

The live scraper can parse server-rendered Nuxt review payloads from Lulus review pages, but local command-line requests began returning PerimeterX captcha/403 responses during the run. Because the workbook already contained review-photo sheets, the final output was generated from the workbook `bigImages` and `oldFormat` sheets instead. Those sheets include product URLs, customer review image URLs, review text, reviewer names, size, color/event/body-type labels, and profile stats.

## Script

`data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_lulus_reviews.py`

The script supports both live Nuxt review-page extraction and workbook-only conversion:

```powershell
python -u data-pipelines\non-amazon\scripts\step_1_raw_scrape\scrape_lulus_reviews.py --skip-live --output-prefix lulus_com
```

## Caveat

This output is not a fresh full live-site crawl. It is a conversion of the existing Lulus workbook review-photo data into the shared Step 1 intake schema, with the local live fetch blocked by PerimeterX captcha/403.

## Continuation - 2026-05-15

The scraper was updated to run on macOS/Linux by selecting `curl` when `curl.exe` is unavailable, and to merge live/workbook rows by product URL plus image URL so mode-specific row IDs do not create duplicates.

A small live smoke continuation briefly succeeded:

- Output CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus_com/lulus_com_live_smoke_20260515_reviews_matching_intake_schema.csv`
- Summary JSON: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus_com/lulus_com_live_smoke_20260515_scrape_summary.json`
- Rows: 4,136 total, including 19 live rows beyond the 4,117 workbook rows
- Distinct product URLs: 23, up from 22 in the workbook-backed file

An immediate follow-up probe returned HTTP 403 for the same first three product review endpoints, so a full live continuation is still blocked by Lulus/PerimeterX from this environment.

## Fresh Live Attempt - 2026-05-15

Added `--live-only` mode to support a true fresh scrape without merging the old workbook rows.

Command used for the probe:

```bash
python -u data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_lulus_reviews.py --live-only --limit-products 10 --workers 1 --delay 1.0 --output-prefix lulus_com_fresh_live_probe_20260515
```

Result:

- Output CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus_com/lulus_com_fresh_live_probe_20260515_reviews_matching_intake_schema.csv`
- Summary JSON: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lulus_com/lulus_com_fresh_live_probe_20260515_scrape_summary.json`
- Rows: 0
- Product URLs processed: 10
- Statuses: all 10 live endpoints returned HTTP 403

Direct PDP fetches also returned the PerimeterX CAPTCHA to local `curl`, and an escalated Playwright/Chromium probe returned HTTP 403 with title `Access to this page has been denied`. A fresh local live scrape is therefore blocked from this environment.
