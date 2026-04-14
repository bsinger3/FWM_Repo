# Procedure: Regenerate Normalized Amazon Data

Use this file as the operating procedure before regenerating:

- `normalized_amazon_data.csv`
- `normalized_amazon_data_preview_1000.csv`

This folder is a CSV/data normalization workspace, not a traditional codebase. Do not infer application logic from source code. Treat the task as an ETL cleanup problem for scraped Amazon review/image data.

## Required References

Read these files first:

- `images_intake_sample - contraints.csv`: formal target schema reference.
- `images_intake_sample - sampleOutput1.csv`: example output shape, but not the complete schema reference.
- `clothingtypes.csv`: allowed `clothing_type_id` labels.
- `measurement_regex_patterns.csv`: approved regex pattern inventory for extracting measurements from `user_comment`.
- `monetized_url_generation_reference.txt`: reference for generating `monetized_product_url_display`.

Do not edit `normalization_plan.txt` unless the user explicitly approves the proposed plan-file change first.

## Input Files

Treat Amazon-named CSV files as candidate raw inputs when regenerating the normalized output. Exclude already-normalized outputs, schema/reference files, regex documentation, and plan/procedure files.

Known raw Amazon inputs include, but may not be limited to:

- `Amazon_2026_Tall - allBigImages.csv`
- `Amazon_prodLinks_jeans_25Feb2026 - allBigImages.csv`
- `amazon_reviews_snowflake_raw_scrape.csv`
- `Amazon Scrape - BigImages.csv`
- `Amazon Scrape - BigImages2.csv`
- `Amazon Scrape - BigImages3.csv`
- `Amazon Scrape - BigImages4.csv`
- `Amazon Scrape 2 - pants_BigImages.csv`

Always assume every input sheet may have shifted or misplaced data. Do not trust column position alone. Use column names when reliable, but also scan row values for URLs, image URLs, product ASINs, date strings, size/color labels, review text, reviewer profile URLs, and other recognizable patterns.

## Output Shape

The normalized output is image-centric: emit one output row per customer image URL.

Use the target schema from `images_intake_sample - contraints.csv`, except ignore these image metadata fields unless the user explicitly asks to fetch image metadata:

- `content_type`
- `bytes`
- `width`
- `height`
- `hash_md5`

Keep database-managed fields blank unless explicitly backfilling:

- `id`
- `created_at_display`

After writing `normalized_amazon_data.csv`, always generate `normalized_amazon_data_preview_1000.csv` as a random sample of 1000 output rows using the same columns.

## URL Rules

`original_url_display` must be the individual customer image URL for the output row.

`product_page_url_display` must always be an Amazon product page URL. It must not be:

- an image URL
- a review URL
- a profile URL
- a search URL
- a seller/storefront URL
- a scraping/source-page URL
- any other non-product Amazon page

If the input only has a review URL such as `/product-reviews/{ASIN}`, extract the ASIN and convert it to a product-page URL. Prefer a canonical product URL shaped like:

```text
https://www.amazon.com/dp/{ASIN}/ref=cm_cr_arp_d_product_top?ie=UTF8
```

When product URLs contain `/dp/{ASIN}` with extra title slug text, they may be preserved if they are valid product pages.

Generate `monetized_product_url_display` using the JavaScript logic documented in `monetized_url_generation_reference.txt`:

```text
http://redirect.viglink.com?key=2aba39b05bc3c8c85f46f6f98c7c728d&u=<encoded_product_page_url_display>
```

The encoding must match JavaScript `encodeURIComponent(product_page_url_display)`.

If `product_page_url_display` is blank or cannot be safely determined as a product page, leave `monetized_product_url_display` blank too.

## Review Text Rules

`user_comment` should contain only the reviewer-written free-form review text, optionally with the review title prepended when it is clearly the review title.

Clean or reject scraped page junk. Do not allow `user_comment` to contain:

- HTML tags
- avatar image tags
- JavaScript snippets
- popover markup
- Amazon image URLs
- repeated Amazon review URLs
- helpful/report/share links or boilerplate
- product-page metadata
- duplicated review text caused by shifted rows
- unrelated page titles or scraping artifacts

If the row is too shifted to confidently isolate reviewer-written text, leave `user_comment` blank rather than carrying forward junk.

## Measurement Extraction Rules

Extract measurements only from cleaned `user_comment`, not from product variant text, page titles, or structured size/color metadata.

Use `measurement_regex_patterns.csv` as the approved pattern inventory. Each row in that file represents one measurement field only. If a phrase contains multiple measurements, apply multiple one-field patterns to the same phrase.

Allowed measurement outputs include fields such as:

- `height_raw`
- `height_in_display`
- `weight_raw`
- `weight_display_display`
- `weight_lbs_display`
- `weight_raw_needs_correction`
- `weight_lbs_raw_issue`
- `waist_raw_display`
- `waist_in`
- `hips_raw`
- `hips_in_display`
- `age_raw`
- `age_years_display`
- `inseam_inches_display`
- `bust_in_number_display`
- `cupsize_display`

Apply exclusion rules before accepting positive matches. In particular, do not treat weight-change phrases as body weight, such as:

- `lost 70 lbs`
- `gained 20 pounds`
- `down 15 lbs`
- `shed 10 pounds`

Validate numeric ranges before writing values. For example:

- height must convert to a plausible adult height
- weight must be a plausible body weight
- waist/hips/bust/inseam/age must be plausible for the field
- fractional heights must be converted correctly, e.g. `5'41/2"` means `64.5`, not `5 feet 41/2 inches`

If a match is ambiguous, prefer leaving the structured field blank over hallucinating a measurement.

## Size And Color Rules

`size_display` and `color_display` should come from structured scraped data whenever possible, not from arbitrary free-form review prose.

Because rows may be shifted, scan row values for explicit structured labels such as:

- `Size: Medium`
- `Color: Black`
- `Fit Type: 25.5" Inseam PetiteSize: MediumColor: Black`
- generated size/color fields when present and clean

Do not over-capture surrounding review text into `color_display` or `color_canonical`. Values like `blackverified purchase...` or `classic blueamazon vine customer review...` are polluted and must be cleaned or blanked.

If `color_canonical` is populated, it must be a normalized color value only. If a reliable canonical mapping is not available, leave it blank.

## Reviewer And Date Rules

`reviewer_name_raw` must be the reviewer name only. If the candidate value appears to be a review title, review body snippet, product title, or page junk, leave it blank.

`reviewer_profile_url` must be an Amazon profile URL only.

For dates:

- Preserve original review-date text in `date_review_submitted_raw` when available.
- Populate `review_date` as ISO `YYYY-MM-DD` only when the date can be parsed confidently.
- Do not infer dates from unrelated scrape timestamps or page metadata.

## Clothing Type Rules

`clothing_type_id` must be one of the labels in `clothingtypes.csv`, normalized consistently for output. Current allowed labels are:

```text
Blouse, Bralette, Bustier, Cami, Culottes, Dress, Gown, Jeans, Jumpsuit, Leggings, Other, Overalls, Pants, Romper, Shirt, Skirt, Sweater, T-Shirt, Tank, Top, Tunic, Vest
```

For output, use the same label semantics consistently, e.g. lowercased values if the existing target output uses lowercased IDs such as `jeans`.

Infer clothing type from reliable product title, source file context, or structured product metadata. If there is no reliable match, use `other` only when the row is definitely a clothing item but the type is unclear; otherwise leave the field blank rather than inventing a type.

## Validation Checklist

Before considering the regenerated output done, run checks for:

- `normalized_amazon_data.csv` exists and is parseable as CSV.
- `normalized_amazon_data_preview_1000.csv` exists and has exactly 1000 data rows, unless the full output has fewer than 1000 rows.
- Preview and full output have identical headers.
- `original_url_display` values are image URLs, not product/review/profile URLs.
- `product_page_url_display` values are product-page URLs, not image URLs or review URLs.
- `monetized_product_url_display` equals the VigLink formula applied to `product_page_url_display`, or is blank when product page URL is blank.
- `user_comment` has no HTML, JavaScript, Amazon URLs, image URLs, helpful/report boilerplate, or obvious duplicated scrape junk.
- `color_display` and `color_canonical` do not contain review prose or Amazon boilerplate.
- `reviewer_name_raw` does not contain review titles or body snippets.
- Measurement fields are populated only from cleaned `user_comment`.
- Weight-change phrases are excluded from body-weight fields.
- `measurement_regex_patterns.csv` has one measurement field per row.
- `clothing_type_id` values are blank or map to a label in `clothingtypes.csv`.

If a row cannot be normalized confidently, keep ambiguous fields blank rather than filling them with guessed values.
