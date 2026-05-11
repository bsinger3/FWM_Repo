# Svaha USA Scrape - 2026-05-11

## Scope

- Merchant: `svahausa.com`
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_svahausa_reviews.py`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/svahausa_com/`
- Output CSV: `svahausa_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `svahausa_com_reviews_matching_amazon_schema_summary.json`

## Source And Coverage

Svaha USA was selected as a first-time scrape after duplicate checks across scripts, docs, claim files, active claim files, and output folders.

Product discovery used the public Shopify catalog:

```text
https://svahausa.com/products.json?limit=250&page=1
```

The public catalog exposed 1,018 unique products across 5 catalog pages. The scraper scanned every catalog product, retained rows only for in-scope adult apparel with deterministic product-description model height/size text, and wrote exclusion reasons for products outside row scope.

Yotpo was visible on product pages and was probed during triage, but the public target-product feed tested returned zero usable customer reviews/media. The completed run therefore uses public Shopify catalog data only and emits catalog-model rows, not customer-review rows.

## Result

- Products discovered: 1,018
- Products scanned: 1,018
- Review pages scanned: 0
- Rows written: 465
- Distinct product URLs in rows: 465
- Rows with customer image: 0
- Rows with catalog model image: 465
- Rows with ordered size: 465
- Rows with measurements: 465
- Supabase-qualified rows: 0
- Catalog-model qualified rows: 465
- Coverage exhaustive: yes, for the public Shopify catalog

The run completed without 429/captcha/WAF behavior.

## Notes

- Rows are `image_source_type=catalog_model_image`; they should not be counted as strict customer-review Supabase-ready rows.
- Size and height parsing is deterministic from explicit product copy such as `Model is 5'7" wearing size S`.
- Customer review coverage is not exhaustive because no usable public customer-review media feed was found during the scrape.
