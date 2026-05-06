# 89th & Madison Scrape - 2026-05-06

## Scope

- Site: `https://89thandmadison.com/`
- Claim: `89thandmadison_com`
- Adapter: `scrape_89thandmadison_reviews.py`
- Discovery method: full public Shopify `products.json` pagination, not aggregate reviews and not just the sheet sample link.
- Image policy: catalog model images only. Rows are marked `image_source_type=catalog_model_image`.

## Results

- Public catalog pages scanned: 4
- Products scanned: 949
- Rows written: 789
- Catalog model image rows: 789
- Supabase-qualified rows with image, product URL, size, and measurement: 789
- Full public catalog scrape complete: yes

## Output

- CSV: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\89thandmadison_com\89thandmadison_com_reviews_matching_intake_schema.csv`
- Summary: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\89thandmadison_com\89thandmadison_com_reviews_matching_intake_schema_summary.json`

## Notes

- The site exposes model measurements in product descriptions, for example height, chest, and worn size.
- Customer-photo review data was not used for this adapter.
- Out-of-scope products such as footwear/accessories were skipped.
- Products without catalog model measurement text were skipped.
