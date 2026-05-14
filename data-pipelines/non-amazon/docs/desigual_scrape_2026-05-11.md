# Desigual Scrape - 2026-05-11

## Status

`desigual_com` is documented as a partial, smoke-verified catalog-model scrape. It is safe to publish as an explicitly partial non-customer-review output, but it should not be treated as a completed full customer-review scrape.

The verified output has zero Supabase-qualified customer-review rows.

## Inputs and Coordination

- Triage target: `desigual.com`, rank 72, manual inspect, provider hint unknown.
- Claim checked and created in `_active_scrape_claims/desigual_com.claim`.
- Prior `_claims` entries were treated as historical context only.
- Access stayed within public resources: robots.txt, public sitemap files, and public product pages.
- No authentication, account pages, private endpoints, captcha handling, WAF handling, or S3 sync workaround was used.

## What Was Found

- `https://www.desigual.com/` redirects to `https://www.desigual.com/en_US/`.
- `robots.txt` advertises `https://www.desigual.com/es_ES/sitemap_index.xml`.
- The sitemap index exposes `sitemap-custom_sitemap_product_es_US.xml`.
- The US product sitemap contained 3,080 URL entries; after canonical URL normalization and duplicate removal, 2,810 product URLs were discovered.
- Product pages are Salesforce Commerce Cloud/Demandware pages with embedded `:initial-product` JSON.
- Product pages can expose deterministic catalog model data:
  - model measurements such as `Height: 180 cm; Waist: 64 cm; Hip: 90 cm`
  - model worn size such as `S/36`
  - product title/category/description
  - catalog model image URLs
- Normal customer review provider markers were not found on the checked homepage/product pages (`Bazaarvoice`, `Yotpo`, `PowerReviews`, `TurnTo` were not present in a usable public review feed).
- Flowbox/NaizFit-style scripts or hints were present, but no public customer-review media feed was identified.

## Output

- Script: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_desigual_reviews.py`
- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/desigual_com/desigual_com_reviews_matching_amazon_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/desigual_com/desigual_com_reviews_matching_amazon_schema_summary.json`

## Metrics

- Run status: `partial_smoke_verified_full_run_deferred`
- Products discovered: 2,810
- Products scanned in saved output: 20
- Products excluded from saved output: 15
- Review pages scanned: 0
- Exhaustive review paging: false
- Rows written: 5
- Distinct images: 5
- Distinct product URLs: 5
- Rows with any measurement: 5
- Rows with customer image: 0
- Rows with catalog model image: 5
- Rows with ordered size/model worn size: 5
- Supabase-qualified customer-review rows: 0
- Catalog-model qualified rows: 5

## Stop / Deferral Note

A full product-page run was started after the smoke run and reached 200 of 2,810 scanned products with 29 catalog-model rows and 171 exclusions. It was manually stopped because product-page throughput was too slow for the repeatedly interrupted thread. No 429, captcha, WAF, HTTP 403, or challenge page was observed before stopping.

The saved CSV/summary intentionally remain the smaller verified 20-product smoke output with a status note marking it partial. This avoids publishing a half-written full run as if it were complete.

## Qualification Notes

The Desigual output uses `image_source_type=catalog_model_image`, not customer-review media. Rows include deterministic model height/waist/hips measurements converted from centimeters to inches and model worn size from the public product page. Because the goal row definition prefers customer review images/text and ordered customer size, `rows_supabase_qualified` remains 0.

## Next Action

Resume later only if a longer-running job is acceptable. The existing script can run the full public sitemap/product-page pass, but it should be allowed enough runtime or be adjusted to checkpoint progress before attempting all 2,810 product pages.
