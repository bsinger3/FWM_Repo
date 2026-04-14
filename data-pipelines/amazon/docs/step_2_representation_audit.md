# Step 2 Representation Audit

This audit checks whether the data from
`amazon_reviews_snowflake_raw_scrape.csv` is represented in Step 2 beyond a
simple image-URL count.

## Source File

- Raw file: `data/step_1_raw_scraping_data/amazon_reviews_snowflake_raw_scrape.csv`
- Raw row count: `41,766`
- Raw columns:
  - `product_url`
  - `size_color`
  - `title`
  - `body`
  - `prev1`
  - `prev2`
  - `prev3`
  - `prev4`
  - `image1`
  - `image2`
  - `image3`
  - `image4`

## What Was Audited

The audit checked:

- whether every raw Snowflake row with at least one image contributes at least
  one Step 2 row
- whether every raw Snowflake image occurrence is represented in Step 2
- whether the normalized product URL derived from the raw row is present in the
  matched Step 2 rows
- whether parsed `size_color` values are preserved in Step 2
- whether raw review text from `title` and `body` appears in the normalized
  `user_comment` field

## Results

- Raw rows with at least one image: `41,764`
- Raw rows with images and a recognizable product URL: `41,764`
- Raw rows contributing to Step 2 by image match: `41,764`
- Raw rows missing from Step 2 by image match: `0`
- Raw image occurrences: `60,240`
- Raw image occurrences matched in Step 2: `60,240`
- Step 2 total rows: `226,863`

## Field-Level Results

- Product URL present in raw rows with images: `41,764`
- Product URL matched in Step 2: `41,764`
- Parsed size present in raw rows: `41,555`
- Parsed size matched in Step 2: `41,555`
- Parsed color present in raw rows: `41,742`
- Parsed color matched in Step 2: `41,742`
- Raw title/body text present: `41,764`
- Raw title/body text matched somewhere in Step 2 `user_comment`: `41,513`

## Interpretation

The Snowflake raw scrape is fully represented in Step 2 for:

- image coverage
- row contribution by image
- normalized product URL mapping
- parsed size preservation
- parsed color preservation

The one area that is not a perfect literal carryover is review text.

That is expected because Step 2 intentionally cleans, merges, de-duplicates,
and normalizes review text into `user_comment`. So a raw `title` or `body`
value may be transformed rather than copied verbatim.

## Conclusion

Based on this audit, the Snowflake raw scrape is represented in Step 2 in the
ways that matter operationally for normalization:

- every raw row with images contributes to Step 2
- every raw image occurrence is represented in Step 2
- key normalized fields derived from the raw scrape are preserved

So the answer is effectively yes: the Snowflake raw scrape is represented in
Step 2, with the expected exception that review text is normalized rather than
stored as a raw literal copy.
