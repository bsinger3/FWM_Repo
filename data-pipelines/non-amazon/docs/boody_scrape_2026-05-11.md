# Boody scrape - 2026-05-11

## Scope

- Retailer: `boody_com`
- Site: `https://boody.com`
- Triage basis: selected as the next unclaimed high-priority scrape after `shapedly_com`, `shoplarken_com`, and `branwyn_com`.
- Target scope: bra products from the verified sheet target. Non-bra products discovered in the Shopify catalog were scanned for catalog reconciliation only and skipped from output.
- Adapter: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_boody_reviews.py`

## Source and access

- Product discovery used public Shopify `products.json` plus the public product sitemap.
- Reviews used the public Yotpo product widget endpoint with app key `ygUpOiL7SxhwQ9SJTqklJMvPoD57lERSu47WhSJI`.
- Customer image rows came from Yotpo review `images_data`.
- No 429, CAPTCHA, WAF, or challenge behavior was observed.

## Extraction notes

- Preserved every usable customer review image row with a product URL.
- Deterministic ordered-size extraction uses Yotpo custom field `Size`, normalized to garment sizes such as `XS`, `S`, `M`, `L`, `XL`, and related alpha variants.
- Deterministic measurement/profile extraction uses public Yotpo custom fields:
  - `Band size` -> `bust_in_number_display`
  - `Cup size` -> `cupsize_display`
- Bra band/cup values are retained as measurements/profile context, not as ordered garment size.
- No measurements were inferred from product titles, variants, or free text.

## Coverage

- Products discovered: 482
- Products target-scanned: 83
- Products excluded from output: 399
- Review pages scanned: 1395
- Product review count hint across target products: 203955
- Rows written: 551
- Distinct reviews: 549
- Distinct images: 551
- Distinct products with output rows: 15

## Required metrics

- Rows with distinct product URL: 15
- Rows with product URL: 551
- Rows with measurement: 73
- Rows with customer image: 551
- Rows with ordered size: 131
- Supabase-qualified rows: 67

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

- CSV: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/boody_com/boody_com_reviews_matching_intake_schema.csv`
- Summary: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/boody_com/boody_com_reviews_matching_intake_schema_summary.json`
- Historical claim: `/Users/briannasinger/Projects/FWM_Data/non-amazon/data/step_1_raw_scraping_data/_claims/boody_com.txt`
