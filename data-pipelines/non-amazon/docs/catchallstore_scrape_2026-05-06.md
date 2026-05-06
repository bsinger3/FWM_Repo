# Catchall Store Scrape - 2026-05-06

## Scope

- Retailer: Catchall Store (`catchallstore.com`)
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_catchallstore_reviews.py`
- Output directory: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\catchallstore_com`
- Access policy: public product pages only; no auth bypass; no captcha bypass; blocked catalog endpoints not retried.

## Discovery

- Seed: `https://catchallstore.com/products/astrid-pink-jacquard-floral-mini-dress`
- Public product page fetch: worked.
- Public catalog/listing endpoints checked and blocked by Cloudflare managed challenge:
  - `/products.json?limit=5&page=1`
  - `/sitemap.xml`
  - `/collections/all`
  - `/ajax/openapi/recommendations/products?...`
- Discovery method used: crawl product links embedded in accessible product pages.
- Products scanned: 23
- Full catalog complete: no, catalog discovery was blocked.

## Output

- Rows written: 14
- Customer review image rows: 0
- Catalog model image rows: 14
- Rows with size: 14
- Rows with measurements: 14
- Supabase-qualified rows under current image+product+size+measurement rule: 14

All emitted rows are marked with:

- `image_source_type=catalog_model_image`
- `image_source_detail=product page catalog/model image; model measurements from product description`

## Notes

- Catchall product descriptions commonly expose model height and worn size, for example `Model is 5 ft 7 and wears size S`.
- Because customer review media was not available through public product pages and catalog endpoints were challenged, this run is a useful catalog-model scrape but not a full sitewide customer-review scrape.
