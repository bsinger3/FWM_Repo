# Ripley Rader Scrape - 2026-05-11

## Scope

- Merchant: `ripleyrader.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_ripleyrader_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/ripleyrader_com/`
- Output CSV: `ripleyrader_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `ripleyrader_com_reviews_matching_amazon_schema_summary.json`

## Source And Coverage

Ripley Rader was selected as a first-time scrape from the 2026-05-11 sheet intake. The sheet note said model measurements only, so the scraper treats rows as `catalog_model_image`, not customer review photos.

Product discovery used:

- Public Shopify catalog: `https://ripleyrader.com/products.json?limit=250&page=1`
- Public Shopify product sitemap: `https://ripleyrader.com/sitemap_products_1.xml`
- Sheet lead URL: `https://ripleyrader.com/products/black-wide-leg-pant-cropped`

Discovery reconciled to 248 unique product URLs. Product pages were scanned for the visible `MODEL:` metafield, then rows were emitted only when that field contained deterministic model height and size text.

## Result

The final saved output is partial because the full regeneration stopped on an HTTP 429, per the scrape rules. No retries were attempted after the 429.

- Products discovered: 248
- Products scanned before stop: 116
- Review pages scanned: 0
- Rows written: 50
- Distinct product URLs in rows: 50
- Rows with customer image: 0
- Rows with catalog model image: 50
- Rows with ordered size: 50
- Rows with measurements: 50
- Supabase-qualified customer-review rows: 0
- Catalog-model qualified rows: 50
- Coverage exhaustive: no

Blocking URL:

```text
https://ripleyrader.com/products/mulberry-jersey-funnel-neck-top
```

Error:

```text
blocked_or_rate_limited_http_429
```

## Notes

- Rows are catalog/model rows only. They should not be counted as customer review image rows.
- Model text is parsed from product-page HTML, not from `products.json`; the catalog JSON lacks the `MODEL:` metafield.
- Some products list multiple models in one metafield. The script keeps the first complete model profile for deterministic height/size parsing on the emitted row.
- A later retry should resume from the first unscanned product after a cool-down window rather than immediately re-probing the 429 URL.
