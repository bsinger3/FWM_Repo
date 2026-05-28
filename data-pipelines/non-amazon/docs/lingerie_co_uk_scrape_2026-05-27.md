# lingerie.co.uk scrape - 2026-05-27

## Source / claim

- Sovrn triage row: `sovrn_first_pass_scrape_candidate`, priority 40 / P2, `lingerie.co.uk`.
- Program: CPC; payout amount not populated.
- Triage signals: reviews present, photo review status `unknown_sample_too_small`, shipping `GB`, provider unknown.
- Seed category: `https://www.lingerie.co.uk/nightdresses-pyjamas`.
- Sample evidence URLs were Magento wishlist-add product IDs; direct fetches redirected to `/enable-cookies`, so they were not used as scrape inputs beyond ID corroboration.

## Implementation

- Added `scripts/step_1_raw_scrape/scrape_lingerie_co_uk_reviews.py`.
- Site implementation is legacy Magento.
- Product discovery uses public category HTML only. The seed category currently exposes 8 products.
- PDP extraction uses public product pages for title, description, price, size/color options, and 700x895 Magento catalog gallery images.
- Review inspection probes the public Magento native route `/review/product/list/id/{product_id}/` for each product. Routes returned 200, but sampled category review bodies were empty and no customer-photo review markup or third-party review widget was found.
- Output therefore uses `image_source_type=catalog_model_image`.

## Output

- CSV: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lingerie_co_uk/lingerie_co_uk_reviews_matching_intake_schema.csv`
- Summary JSON: `FWM_Data/non-amazon/data/step_1_raw_scraping_data/lingerie_co_uk/lingerie_co_uk_reviews_matching_intake_schema_summary.json`

Final run metrics:

- Products discovered/scanned: 8 / 8
- Rows written: 8
- Columns: 51 intake-schema columns
- Catalog model image rows: 8
- Customer review image rows: 0
- Rows with size options: 5
- Rows with blank image URL: 0
- Rows with blank product URL: 0
- Errors / stop reason: none
- Coverage: exhaustive for the source category, not full catalog

## Access notes

- Public category, PDP, and native review pages only.
- No login, cart, wishlist, review submission, captcha, or WAF bypass attempted.
- Stop conditions were configured for 429, captcha, WAF, and auth/cookie-gated behavior.
