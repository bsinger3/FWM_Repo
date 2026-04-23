# New Scrape Rules

This document is the checklist for adding a new retailer scrape to Friends With
Measurements. A scrape is useful only if each output row can become a clickable
image card with enough fit context for shoppers.

## Goal

Each scrape should produce review-image rows from public retailer review pages.
The preferred output is a CSV that matches the existing Amazon-style intake
schema used by Step 1 raw scraping data.

The current site scope is women's clothing only. Do not add men's, kids',
unisex-only, accessories-only, shoes-only, or non-clothing products to publish
ready scrape outputs unless the project scope changes.

Use one row per review image. If a single review has multiple usable shopper
photos, emit one row for each image and duplicate the review/product metadata
across those rows.

## Output Location And Naming

For non-Amazon retailers, write outputs under:

```text
data-pipelines/non-amazon/data/step_1_raw_scraping_data/<retailer>/
```

Use these filenames:

```text
<retailer>_reviews_matching_amazon_schema.csv
<retailer>_reviews_matching_amazon_schema_summary.json
```

The summary JSON should include at least:

- `site`
- `products_scanned` or equivalent page/review count
- `rows_written`
- `distinct_reviews`
- `distinct_images`
- `output_csv`
- `started_at`
- `finished_at`

## Step 1 Intake Data

Step 1 raw scrape outputs should be inclusive. Do not drop a review-photo row
only because size or body measurements are not available as structured fields.
Those values are often written in `user_comment`, and later standardization can
extract them with regex.

A Step 1 row should have:

- `original_url_display`: non-empty image URL.
- `product_page_url_display` or `monetized_product_url_display`: product URL.
- `user_comment`: review text whenever available, especially when it may
  contain size, height, weight, bust, waist, hips, or fit notes.
- Women's-clothing scope confidence from product title/category/metadata.

Populate structured size and measurement fields during the scrape when they are
obvious, but leave them blank rather than dropping the row or guessing.

## Publish-Ready Card Data

A row should not be inserted into `public.images`, and will not display on the
frontend, unless it has all of these after standardization/enrichment:

- `original_url_display`: non-empty image URL.
- `size_display`: valid ordered size, not blank and not `unknown`.
- At least one body measurement:
  - `height_in_display`
  - `weight_display_display`
  - `bust_in_number_display`
  - `hips_in_display`
  - `waist_in`
- At least one product URL:
  - `monetized_product_url_display`
  - `product_page_url_display`

Database constraints also require:

- `original_url_display` is present and not blank.
- At least one product URL is present.
- `size_display` is present.

## Standard Output Columns

Scrapers should output these columns when available:

```text
created_at_display
id
original_url_display
product_page_url_display
monetized_product_url_display
height_raw
weight_raw
user_comment
date_review_submitted_raw
height_in_display
review_date
source_site_display
status_code
content_type
bytes
width
height
hash_md5
fetched_at
updated_at
brand
waist_raw_display
hips_raw
age_raw
waist_in
hips_in_display
age_years_display
search_fts
weight_display_display
weight_raw_needs_correction
clothing_type_id
reviewer_profile_url
reviewer_name_raw
inseam_inches_display
color_canonical
color_display
size_display
bust_in_number_display
cupsize_display
weight_lbs_display
weight_lbs_raw_issue
```

Some older scraper outputs omit a few optional columns, but new scrapes should
prefer the fuller schema above.

## Field Rules

### URLs

- `original_url_display` must point to the shopper review image, not a product
  catalog image.
- `product_page_url_display` should point to the retailer product page.
- `monetized_product_url_display` may be blank when unavailable.
- `reviewer_profile_url` is optional, but capture it when the retailer exposes
  it publicly.

### Review Text And Dates

- `user_comment` should contain the review body or a useful combination of
  title/body text.
- `date_review_submitted_raw` should preserve the raw retailer date string.
- `review_date` should be normalized when possible.

### Measurements

Preserve raw strings and also populate normalized fields when possible:

- `height_raw` and `height_in_display`
- `weight_raw` and `weight_display_display` / `weight_lbs_display`
- `waist_raw_display` and `waist_in`
- `hips_raw` and `hips_in_display`
- `age_raw` and `age_years_display`
- `inseam_inches_display`
- `bust_in_number_display`
- `cupsize_display`

Numeric normalized fields must contain only numeric values if present. Leave
them blank rather than guessing.

Do not reject a raw scrape row just because these structured fields are blank.
If the review comment says something like "I'm 5'4, 165 lbs, ordered XL," keep
the row and preserve the comment so later regex extraction can populate the
normalized fields.

### Size

- `size_display` is mandatory for publishable rows, but not mandatory for raw
  Step 1 scrape rows when size may be present in `user_comment`.
- Do not emit blank, `unknown`, or vague size values for rows intended for
  `public.images`.
- For bra-size products, split the size into:
  - `bust_in_number_display` for band size.
  - `cupsize_display` for cup size.

### Product Metadata

Capture product metadata during scraping. Do not rely only on URL slugs because
some retailer links collapse to opaque IDs.

Prefer category and product interpretation from these sources, in order:

1. Explicit product metadata from the retailer page:
   - product name/title
   - product subtitle
   - product description
   - product detail bullets
2. Rich product URL slug.
3. Existing trusted `clothing_type_id`.
4. Manual metadata review.

Do not use review text as the primary source for product category unless the row
is explicitly low-confidence or manual-assisted. Review text often mentions
other garments, styling ideas, or comparisons that are not the reviewed product.

### Clothing Type

- `clothing_type_id` is optional, but if present it must match
  `public.clothing_types.id`.
- Use lowercase canonical values, for example `jeans`, `pants`, `dress`, or
  `top`.
- Only scrape and classify women's clothing under the current product scope.
- If category confidence is low, leave it blank or route the row for manual
  review rather than inventing a value.

### Image Quality

The image should be useful for judging how clothing fits on a real shopper.
Reject or route for later review when:

- no person is visible
- the image is only a tag, label, packaging shot, flat-lay, or catalog image
- the reviewed product is not visible enough to assess fit
- multiple people make it unclear which person/product is being reviewed
- the image does not match the reviewed product
- the reviewed product is outside the current women's-clothing scope

## Scraper Behavior

- Prefer retailer review APIs, embedded review JSON, or public review widgets
  when available.
- Use stable product discovery sources such as product sitemaps, collection
  pages, or all-reviews endpoints.
- Use a normal browser user agent and retry transient failures.
- Track `fetched_at` and `updated_at` using ISO-like timestamps.
- Keep the raw values even when normalized parsing succeeds.
- Deduplicate repeated images/reviews where practical.
- Do not silently coerce suspicious values. Mark issue columns such as
  `weight_raw_needs_correction` or `weight_lbs_raw_issue` when needed.

## Validation Before Handoff

Before considering a scrape ready for the next pipeline step:

- Confirm the CSV header matches the standard schema as closely as possible.
- Confirm every raw Step 1 row has image URL, product URL, and review text when
  available.
- Confirm rows are not being dropped solely because size or measurement values
  require later regex extraction from `user_comment`.
- For publish-ready rows, confirm image URL, product URL, size, and at least one
  body measurement.
- Confirm numeric normalized fields are numeric or blank.
- For publish-ready rows, confirm `size_display` is not blank or `unknown`.
- Confirm the reviewed product is women's clothing.
- Confirm image URLs load and are shopper-review images.
- Confirm product URLs load.
- Confirm `source_site_display`, `brand`, `fetched_at`, and `updated_at` are
  populated.
- Confirm the summary JSON counts match the CSV.

## Handoff To Later Steps

Step 1 raw scrape outputs feed later standardization, image annotation, CV /
human approval, and Step 5 publish-ready outputs. Rows can still be rejected
later for image usefulness, category ambiguity, duplicate images, dead links, or
incorrect measurements.

The scrape should therefore preserve enough context for audit and manual review:

- source URL
- product URL
- image URL
- reviewer name/profile when available
- raw review text
- raw and normalized measurement values
- product title/description/detail text when available
- assigned category and confidence when category logic is used

## Repo References

- `image-approval-context.md`
- `data-pipelines/amazon/docs/images_intake_sample - contraints.csv`
- `data-pipelines/amazon/docs/images_intake_sample - sampleOutput1.csv`
- `data-pipelines/non-amazon/scripts/step_1_raw_scrape/`
- `supabase/migrations/20260413141641_remote_schema.sql`
- `index.html`
