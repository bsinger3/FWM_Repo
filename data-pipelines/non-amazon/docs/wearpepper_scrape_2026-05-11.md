# Wear Pepper scrape - 2026-05-11

## Scope

- Retailer: `wearpepper_com`
- Site: `https://www.wearpepper.com`
- Triage basis: selected as the next unclaimed first-time scrape from verified sheet intake after skipping previously claimed/completed retailers.
- Adapter: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_wearpepper_reviews.py`
- Target scope: women's clothing products. Accessories, bundles, gift cards, and non-single-product packs were counted in coverage and excluded from row output with skip reasons.

## Source and access

- Product discovery used public Shopify `products.json` and the public product sitemap.
- Reviews used the public Judge.me `reviews_for_widget` JSON endpoint for `pepper-bra.myshopify.com`.
- Review paging used `sort_by=with_pictures` to exhaust public media-bearing review pages without crawling grouped text-only review history.
- No 429, CAPTCHA, WAF, or challenge behavior was observed.

## Extraction notes

- Preserved every usable customer review image row exposed in public Judge.me review media.
- Ordered size was extracted deterministically from Judge.me `product_variant_title` and custom answers when exposed.
- Bra sizes such as `34A` were normalized and may populate bra band/cup profile fields through the shared Step 1 parser.
- Additional public review text and Judge.me custom answers were preserved in `user_comment`.
- No measurements or sizes were inferred beyond explicit review fields/text and existing deterministic parser behavior.

## Coverage

- Products discovered: 310
- Products target-scanned: 236
- Products excluded from output: 74
- Review pages scanned: 442
- Product review count hint across scanned products: 220144
- Rows written: 1150
- Distinct reviews: 814
- Distinct images: 1150
- Distinct products with output rows: 161

## Required metrics

- Rows with distinct product URL: 161
- Rows with product URL: 1150
- Rows with measurement: 445
- Rows with customer image: 1150
- Rows with ordered size: 497
- Supabase-qualified rows: 430

## Validation

- Recomputed CSV metrics independently against intake schema columns.
- Summary JSON and recomputed CSV metrics match after normalizing `rows_with_any_measurement` to the strict required measurement field set.
- Blank image URLs: 0
- Blank product URLs: 0
- Invalid normalized numeric fields reported by scraper:
  - `height_in_display`: 0
  - `waist_in`: 0
  - `hips_in_display`: 0
  - `inseam_inches_display`: 0
  - `bust_in_number_display`: 0
- Script compiled with `python3 -m py_compile`.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wearpepper_com/wearpepper_com_reviews_matching_intake_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/wearpepper_com/wearpepper_com_reviews_matching_intake_schema_summary.json`
- Historical claim: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/_claims/wearpepper_com.txt`
