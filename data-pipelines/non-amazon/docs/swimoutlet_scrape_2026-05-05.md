# SwimOutlet scrape attempt - 2026-05-05

## Scope

- Retailer: SwimOutlet (`swimoutlet.com`)
- Step: non-Amazon Step 1 raw scraping data
- Adapter: Okendo product-level reviews
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_swimoutlet_reviews.py`
- Output directory: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\swimoutlet_com`
- Access policy: public product and review pages only; no auth bypass; no captcha bypass; polite retries

## What Worked

- Added an active claim at `_active_scrape_claims\swimoutlet_com.claim`.
- Confirmed public Shopify catalog endpoint: `https://www.swimoutlet.com/products.json`.
- Confirmed public Okendo store ID: `2915ad0c-3ac4-4e21-b85f-e0308a320c04`.
- Confirmed known seed product reviews return image rows and ordered size/color through Okendo `productVariantName`, for example `Multi / 36`.

## Blocker

- A 5-product smoke run completed but wrote 0 rows because the newest catalog products had no photo reviews.
- The full catalog attempt discovered 1,750 products from `products.json` pages 1-7.
- The attempt then hit `HTTP 429 Too Many Requests` on `products.json` page 8.
- The run was stopped immediately to avoid suspicious or high-pressure traffic.

## Current Output Status

- The current SwimOutlet CSV is a smoke/blocker artifact, not a complete scrape.
- Do not treat `rows_written: 0` as final retailer coverage.
- The prior seed-only output was superseded by the smoke run, so SwimOutlet should stay on the revisit list.

## Revisit Plan

- Wait for a later scrape window before retrying.
- Add catalog checkpoint/resume so discovered product pages are preserved if a later page hits 429.
- Retry with `--request-delay-seconds 2.0` or slower.
- Keep the active claim file until either the scrape is resumed or the claim is intentionally released.
