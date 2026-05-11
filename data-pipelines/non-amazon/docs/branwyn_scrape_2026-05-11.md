# BRANWYN Scrape 2026-05-11

## Scope

- Site: branwyn.com
- Triage source: `scrape_triage_plan.md` Sheet Intake Added 2026-05-06, `branwyn_com`: two bra/bralette targets.
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_branwyn_reviews.py`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/branwyn_com/`
- Adapter: public Shopify catalog plus product-level Judge.me `reviews_for_widget`

## Coverage

- Products discovered: 24
- Products scanned: 24
- Products excluded from output: 5
- Product-level review pages scanned: 30
- Exhaustive review paging: true
- Product review count hint: 342

All public Shopify products were discovered from `products.json` and reconciled with the product sitemap. Accessories, gift card, and carbon-offset products were counted and marked as skipped in `product_summaries`.

## Extraction Notes

The scraper uses product-level Judge.me review widgets with `sort_by=with_pictures`. It emits one row per unique customer review image after normalizing Judge.me image URL variants by removing query parameters.

Ordered size is restricted to deterministic garment-size tokens for BRANWYN's alpha-sized products, such as `small`, `medium`, `large`, `x-large`, and related variants. Bra band/cup values such as `34DD` are treated as body/profile measurements through `bust_in_number_display` and `cupsize_display`, not as ordered product sizes.

No measurements or sizes are inferred beyond deterministic public review text parsing.

## Output Metrics

- Rows written: 426
- Distinct reviews: 307
- Distinct images: 426
- Rows with product URL: 426
- Rows with a distinct product URL: 17
- Rows with at least one measurement: 178
- Rows with customer image: 426
- Rows with the size the customer ordered: 137
- Supabase-qualified rows: 91

## Validation

- CSV and summary counts were recalculated from disk and matched the summary JSON.
- Numeric normalized fields checked clean.
- No blank image URL rows.
- No blank product URL rows.
- Full run completed without HTTP 403, HTTP 429, captcha, or challenge behavior.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/branwyn_com/branwyn_com_reviews_matching_intake_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/branwyn_com/branwyn_com_reviews_matching_intake_schema_summary.json`
