# Victoria's Secret Scrape - 2026-05-06

## Scope

- Site: `https://www.victoriassecret.com/`
- Claim: `victoriassecret_com` / canonical output slug `vs`
- Adapter: `scrape_victoriassecret_reviews.py`
- Discovery method: every product URL in the local `VSprodLinks` catalog sheet was scanned. This is not just the sample lead URL and not an aggregate-review scrape.
- Review source: public Victoria's Secret ratings-and-reviews API filtered by variant/product review data.
- Catalog model source: public Victoria's Secret product API structured on-model image and model profile data.

## Results

- Product URLs scanned: 140
- Rows written: 1,177
- Customer review image rows: 1,029
- Catalog model image rows: 148
- Supabase-qualified rows with image, product URL, size, and measurement: 320
- Errors: 0

## Output

- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\vs\vs_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\vs\vs_reviews_matching_intake_schema_summary.json`

## Notes

- The prior workbook-only conversion was replaced by a live public API scrape over the local product catalog URLs.
- Rows are deduped by row id plus image URL so customer review photos and catalog model images repeated across color URLs do not inflate the output.
- `full_catalog_scrape_complete` remains `false` because this run covers the local VS product catalog sheet, not independently discovered sitewide VS inventory.
