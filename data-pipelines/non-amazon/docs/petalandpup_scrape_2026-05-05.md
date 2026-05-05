# Petal & Pup Scrape Notes - 2026-05-05

## Outcome

- Retailer: `petalandpup_com`
- Site: `https://petalandpup.com/`
- Output CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/petalandpup_com/petalandpup_com_reviews_matching_intake_schema.csv`
- Summary JSON: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/petalandpup_com/petalandpup_com_reviews_matching_intake_schema_summary.json`
- Rows: 947 review image rows
- Qualified rows: 688 rows with image, product URL, size, and at least one measurement/profile field
- Distinct product URLs with image rows: 126
- Apparel products scanned: 705

## Method

Product discovery used public Shopify `products.json` pages 1-3, which returned 750 products. The scraper filtered that set to 705 apparel products.

Review extraction used the public Yotpo widget JSON endpoint keyed by Shopify product ID:

`https://api-cdn.yotpo.com/v1/widget/{app_key}/products/{product_id}/reviews.json`

Yotpo exposed customer review image URLs in `images_data` and customer profile/custom fields such as `Size`, `Height`, `Weight`, and `Bust Size`.

## Caveat

This is a bounded partial catalog scrape, not a full catalog scrape. `products.json` returned HTTP 429 on page 4 during the first attempt. A sitemap-based full catalog fallback found 6,734 product URLs, but fetching product `.js` metadata for those URLs later also hit HTTP 429. The final output intentionally uses the already available `products.json` pages 1-3 to avoid repeat pressure.

## Script

`data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_petalandpup_reviews.py`

Bounded run used:

```powershell
python -u data-pipelines\non-amazon\scripts\step_1_raw_scrape\scrape_petalandpup_reviews.py --limit-catalog-pages 3 --workers 4 --catalog-delay 0.5 --review-delay 0.05 --output-prefix petalandpup_com
```
