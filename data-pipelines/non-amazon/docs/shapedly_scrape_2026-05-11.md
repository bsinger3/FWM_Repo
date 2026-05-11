# Shapedly Scrape 2026-05-11

## Scope

- Site: shapedly.com
- Script: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_shapedly_reviews.py`
- Data root: `/Users/briannasinger/Projects/FWM_Data`
- Output directory: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/shapedly_com/`
- Adapter: public LAI Reviews product-level `load-more` endpoint

## Triage Finding

The prior Shapedly output had strong review-media yield but zero Supabase-qualified rows because `size_display` was always blank. LAI `cf_answers` was present in the review shape but not populated in sampled public Shapedly reviews, so ordered size is available only when reviewers wrote explicit size/order phrases in the public review body.

The scraper now deterministically extracts ordered size from explicit phrases such as `Ordered an XL`, `bought ... size Medium`, `went with a size medium`, and `Got a large`. It also keeps all image rows even when no size or measurement can be extracted, and marks LAI review photos with `image_source_type=customer_review_image`.

Measurement parsing was also widened for public body text formats seen in Shapedly reviews:

- compact height with double quote used as a foot marker, such as `4”11`
- weight near height without an explicit pound unit, such as `I’m 180 5’8`

No measurements or ordered sizes are inferred beyond deterministic public text patterns.

## Coverage

- Products discovered: 59
- Products scanned: 59
- Products excluded from output: 4
- Review pages scanned: 132
- Exhaustive review paging: true
- Product review count hint: 27,095
- Distinct products with output rows: 9

Out-of-scope product rows were counted in `product_summaries` and skipped from output for gift card, washing bag, nipple covers, and shipping protection.

## Output Metrics

- Rows written: 764
- Distinct reviews: 370
- Distinct images: 764
- Rows with product URL: 764
- Rows with a distinct product URL: 9
- Rows with at least one measurement: 282
- Rows with customer image: 764
- Rows with customer review image: 764
- Rows with the size the customer ordered: 175
- Supabase-qualified rows: 135

## Validation

- CSV and summary counts were recalculated from disk and matched the summary JSON.
- Numeric normalized fields checked clean: no non-numeric values in height, weight, bust, waist, hips, inseam, or age numeric columns.
- No blank image URL rows.
- No blank product URL rows.
- No homepage/root URLs in product URL rows.
- Full run completed without HTTP 403, HTTP 429, captcha, or challenge behavior.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/shapedly_com/shapedly_com_reviews_matching_amazon_schema.csv`
- Summary JSON: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/shapedly_com/shapedly_com_reviews_matching_amazon_schema_summary.json`
