# Shop Larken Scrape 2026-05-11

## Scope

- Site: shoplarken.com
- Triage source: `scrape_triage_plan.md` Sheet Intake Added 2026-05-06, `shoplarken_com`: bra target with Judge.me anchor.
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_shoplarken_reviews.py`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/shoplarken_com/`
- Adapter: public Shopify catalog plus product-level Judge.me `reviews_for_widget`

## Coverage

- Products discovered: 12
- Products scanned: 12
- Products excluded from output: 1 gift card
- Product-level review pages scanned: 11
- Exhaustive review paging: true
- Product review count hint: 24

All public Shopify products were discovered from `products.json` and reconciled with the product sitemap. Clothing products with zero public review photos were scanned and retained in `product_summaries`.

## Extraction Notes

Judge.me custom-form fields expose:

- customer bra size, such as `Size: 36D`
- ordered product size, such as `Size purchased: M`

The scraper appends these public custom fields to `user_comment`, writes ordered size to `size_display`, and lets the shared deterministic parser populate bust/cup fields from the customer bra size. No measurements or sizes are inferred.

Judge.me repeats the same Larken X review images across color/sibling product widgets. The scraper dedupes by `(review_id, image_url)` after product-level scanning, so repeated image rows are not inflated across sibling product pages.

## Output Metrics

- Rows written: 14
- Distinct reviews: 6
- Distinct images: 14
- Rows with product URL: 14
- Rows with a distinct product URL: 1
- Rows with at least one measurement: 4
- Rows with customer image: 14
- Rows with the size the customer ordered: 6
- Supabase-qualified rows: 4

## Validation

- CSV and summary counts were recalculated from disk and matched the summary JSON.
- Numeric normalized fields checked clean.
- No blank image URL rows.
- No blank product URL rows.
- Full run completed without HTTP 403, HTTP 429, captcha, or challenge behavior.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/shoplarken_com/shoplarken_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/shoplarken_com/shoplarken_com_reviews_matching_intake_schema_summary.json`
