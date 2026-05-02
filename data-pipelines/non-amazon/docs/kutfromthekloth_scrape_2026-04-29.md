# Kut From The Kloth Scrape - 2026-04-29

## Scope

- Retailer: Kut from the Kloth
- Site: `https://kutfromthekloth.com`
- Scraper: `data-pipelines/non-amazon/scripts/step_1_raw_scrape/scrape_kutfromthekloth_reviews.py`
- Adapter: Okendo product-level reviews
- Data output: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\kutfromthekloth_com\kutfromthekloth_com_reviews_matching_intake_schema.csv`
- Summary output: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\non-amazon\data\step_1_raw_scraping_data\kutfromthekloth_com\kutfromthekloth_com_reviews_matching_intake_schema_summary.json`

## Result

The final run used product-level scraping, not aggregate-only scraping.

- Products discovered: 444
- Products scanned: 444
- Products with review rows: 79
- Review pages scanned: 412
- Rows written: 256
- Distinct reviews: 187
- Distinct images: 256
- Distinct product URLs: 54
- Rows with product URL: 256
- Rows with at least one measurement: 98
- Rows with customer image: 256
- Rows with customer ordered size: 217
- Supabase-qualified rows: 85
- Distinct qualified reviews: 49
- Errors: 0

The scraper records `aggregate_only: false` and
`measurement_extraction: deterministic_regex_and_provider_fields_only` in the
summary JSON.

## Implementation Notes

- Product discovery used Shopify `/products.json`.
- Reviews were collected per product from Okendo using product IDs.
- Okendo relative `nextUrl` pagination needed to be resolved against
  `https://api.okendo.io/v1`.
- The image URL parser had to recognize image URLs embedded in Okendo payloads.
- Deduplication is by review ID and image key so grouped Okendo reviews do not
  create duplicate customer-image rows across sibling product URLs.
- The final data was synced to S3 after the successful run.

## Retrospective

Most rows that did not qualify were missing customer measurements, not product
URLs or customer images.

- Missing measurement: 158 rows
- Measurement present but ordered size missing: 13 rows
- Qualified: 85 rows

There is one realistic way to recover more qualified rows without using an LLM:
add a conservative deterministic ordered-size fallback from review text when
Okendo does not provide `productVariantName`. In the final CSV, 7 rows looked
recoverable by high-confidence text patterns such as "ended up sending back for
a 00", "ordered a 4", and "go up to a 16". Another 3 rows had inline size
phrases such as "size 2" or "Sz. 6" that may be recoverable with stricter
context checks.

Do not increase the qualified count by re-expanding grouped Okendo repeats or
image-size variants. That would inflate duplicate review/image rows rather than
produce new canonical Supabase-ready rows.

## Follow-Up

- Add deterministic ordered-size fallback patterns for explicit purchase,
  exchange, and wearing language.
- Improve height parsing for formats like `5'-7"` so inches are not dropped.
- Consider a deterministic contextual weight parser for phrases like
  `5'4", 114` when height and weight appear together, while keeping raw values
  auditable.
