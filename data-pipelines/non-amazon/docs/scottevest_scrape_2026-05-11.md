# SCOTTeVEST scrape - 2026-05-11

## Scope

- Retailer: `scottevest_com`
- Site: `https://www.scottevest.com`
- Triage basis: selected as the next first-time scrape from verified sheet intake after skipping completed, blocked, or active merchants.
- Adapter: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_scottevest_reviews.py`
- Target scope: women's clothing products. Men's, unisex-only, gift, and non-clothing rows were counted in coverage and excluded from output with skip reasons.

## Source and access

- Product discovery used public Shopify `products.json` plus the public product sitemap.
- Reviews used the public Okendo product review JSON endpoint for each discovered Shopify product ID.
- The run scanned the full public product catalog discovered by those sources and paged product-level Okendo reviews until each product's public review feed ended.
- No 429, CAPTCHA, WAF, or challenge behavior was observed.

## Extraction notes

- Preserved every usable public Okendo customer review image row for in-scope women's clothing.
- Ordered size was populated from Okendo `productVariantName` or explicit product attribute fields when present.
- Reviewer profile/body fields, including height and body type, were preserved in `user_comment`; deterministic shared parsing populated structured measurements only when explicit.
- No measurements or sizes were invented from product titles, review sentiment, or non-explicit text.

## Coverage

- Products discovered: 71
- Products scanned: 71
- Products target-scanned: 32
- Products excluded from output: 39
- Review pages scanned: 135
- Product review count hint across scanned products: 10,573
- Rows written: 207
- Distinct reviews: 156
- Distinct images: 207
- Distinct products with output rows: 27

## Required metrics

- Rows with distinct product URL: 27
- Rows with product URL: 207
- Rows with measurement: 199
- Rows with customer image: 207
- Rows with ordered size: 167
- Supabase-qualified rows: 163

## Validation

- Recomputed CSV metrics independently against intake schema columns.
- Summary JSON and recomputed CSV metrics match.
- Blank image URLs: 0
- Blank product URLs: 0
- Invalid normalized numeric fields reported by validation:
  - `height_in_display`: 0
  - `waist_in`: 0
  - `hips_in_display`: 0
  - `inseam_inches_display`: 0
  - `bust_in_number_display`: 0
- Script compiled with `python3 -m py_compile`.

## Outputs

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/scottevest_com/scottevest_com_reviews_matching_intake_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/scottevest_com/scottevest_com_reviews_matching_intake_schema_summary.json`
- Historical claim: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/_claims/scottevest_com.txt`
