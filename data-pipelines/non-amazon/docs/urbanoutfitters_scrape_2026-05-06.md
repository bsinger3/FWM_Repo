# Urban Outfitters Scrape - 2026-05-06

## Scope

- Site: `https://www.urbanoutfitters.com/`
- Claim: `urbanoutfitters_com` / output slug `urban_outfitters`
- Adapter: `scrape_urbanoutfitters_reviews.py`
- Discovery method: every product URL in the local `UO_BigImages.xlsx` `prodLinks` catalog sheet was queued. This was not an aggregate-review scrape and not just the sample links.
- Review source: direct public review API probing was stopped because the endpoint returned a DataDome interstitial.
- Catalog model source: public product-page SSR `urbnInitialPiniaState` payload with catalog/model images plus model notes and size/fit measurements.

## Results

- Product URLs discovered in workbook catalog: 371
- Product pages attempted before access stop: 10
- Product pages parsed before stop: 8
- Rows written: 158
- Customer review image rows: 0
- Catalog model image rows: 158
- Supabase-qualified rows with image, product URL, size, and measurement: 158
- Stop reason: first HTTP 403 from public product page; scraper stopped per no-bypass guardrail.

## Output

- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\urban_outfitters\urban_outfitters_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\urban_outfitters\urban_outfitters_reviews_matching_intake_schema_summary.json`

## Notes

- Output rows are marked `image_source_type=catalog_model_image`.
- `image_source_detail` records that the image came from the public UO product page catalog/model image and measurements came from SSR product state.
- The customer review API path discovered in the bundled JS was not used because public probes returned a DataDome interstitial.
- `full_catalog_scrape_complete=false` because the run stopped at the first HTTP 403 and because the source catalog was the local workbook, not independently discovered sitewide inventory.
