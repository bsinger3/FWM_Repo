# ThirdLove scrape - 2026-05-11

## Scope

- Retailer: `thirdlove_com`
- Site: `https://www.thirdlove.com`
- Triage basis: selected from verified sheet intake as the next first-time bra target after skipping completed, blocked, or active sites.
- Adapter: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_thirdlove_reviews.py`
- Target scope: women's clothing products. Accessories, bundles, gift cards, and non-single-product packs were counted in coverage and excluded from row output with skip reasons.

## Source and access

- Product discovery used public Shopify `products.json` plus the public product sitemap.
- Reviews used the public Yotpo product widget JSON endpoint with app key `rY9GSntV8qMS3mVnRNBzVIaznqMp8VJiTDyl1Cjr`.
- Review paging used Yotpo `sort=images` and stopped after media-bearing rows were exhausted for each product.
- No 429, CAPTCHA, WAF, or challenge behavior was observed.

## Extraction notes

- Preserved every usable public Yotpo customer review image row.
- Public Yotpo custom fields expose profile data such as fit/comfort/cup size on some rows. These fields were preserved in `user_comment`; deterministic shared parsing populated structured fields only when explicit.
- Ordered size was populated only when deterministic shared parsing found explicit size text.
- No measurements or sizes were invented from product variants, product titles, or review sentiment.

## Coverage

- Products discovered: 373
- Products target-scanned: 317
- Products excluded from output: 56
- Review pages scanned: 528
- Product review count hint across scanned products: 1203951
- Rows written: 94
- Distinct reviews: 69
- Distinct images: 94
- Distinct products with output rows: 20

## Required metrics

- Rows with distinct product URL: 20
- Rows with product URL: 94
- Rows with measurement: 18
- Rows with customer image: 94
- Rows with ordered size: 34
- Supabase-qualified rows: 18

## Validation

- Recomputed CSV metrics independently against intake schema columns.
- Summary JSON and recomputed CSV metrics match.
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

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/thirdlove_com/thirdlove_com_reviews_matching_intake_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/thirdlove_com/thirdlove_com_reviews_matching_intake_schema_summary.json`
- Historical claim: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/_claims/thirdlove_com.txt`
