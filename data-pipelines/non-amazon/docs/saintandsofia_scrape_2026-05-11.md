# Saint + Sofia Scrape - 2026-05-11

## Scope

- Merchant: `saintandsofia.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_saintandsofia_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/saintandsofia_com/`
- Output CSV: `saintandsofia_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `saintandsofia_com_reviews_matching_amazon_schema_summary.json`

## Source And Coverage

Saint + Sofia was selected as a first-time scrape after a duplicate check across scraper scripts, merchant docs, claim files, active claim files, and output directories.

Product discovery used the public Shopify catalog:

```text
https://saintandsofia.com/products.json?limit=250&page=N
```

The catalog exposed 987 products across four pages. Product-page HTML contains catalog model fit text such as `Model: 5’8” wearing size US 4.` The scraper is designed to emit `catalog_model_image` rows from that deterministic product-page text.

## Result

The smoke scrape stopped immediately on an HTTP 429 while fetching the 10th product page. No retry was attempted after the 429.

- Products discovered: 987
- Products scanned before stop: 9
- Review pages scanned: 0
- Rows written: 0
- Distinct product URLs in rows: 0
- Rows with customer image: 0
- Rows with catalog model image: 0
- Rows with ordered size: 0
- Rows with measurements: 0
- Supabase-qualified customer-review rows: 0
- Catalog-model qualified rows: 0
- Coverage exhaustive: no

Blocking URL:

```text
https://saintandsofia.com/products/adjustable-wide-leg-jean-leopard
```

Error:

```text
blocked_or_rate_limited_http_429
```

## Notes

- The site should not be retried immediately. Wait for a later cool-down window.
- The scraper was patched after the smoke run so it will correctly parse the `Care & Fit` `Model:` line on a future resume.
- A future resume should start slowly from the unscanned tail and should keep using public pages/endpoints only.
