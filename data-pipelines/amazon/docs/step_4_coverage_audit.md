# Step 4 Coverage Audit

This audit compares the current Step 3 machine-annotated outputs against the
current Step 4 incomplete human review sample files.

## Summary

- Step 3 machine-annotated chunk files: `31`
- Step 4 human review files currently present: `1`
- Step 3 total rows: `91,925`
- Step 4 total rows: `2,932`
- Step 3 distinct image URLs: `67,711`
- Step 4 distinct image URLs: `2,924`
- Distinct image URLs missing from Step 4: `64,787`
- Extra Step 4 image URLs not found in Step 3: `0`
- Current Step 4 distinct URL coverage of Step 3: `4.32%`

## Current State

The current Step 4 folder does **not** yet represent the full Step 3 image set.

What exists today:

- one incomplete human review comparison file:
  `ImageFlags - images_to_approve_part_002.csv`

What does not yet exist:

- a full Step 4 review-sheet set covering all Step 3 machine-annotated rows

## Chunk 2 Snapshot

For the currently reviewed sample file:

- Step 3 part 002 rows: `3,000`
- Step 4 part 002 rows: `2,932`
- Step 3 part 002 distinct image URLs: `2,992`
- Step 4 part 002 distinct image URLs: `2,924`

So even the one existing Step 4 sample file is incomplete relative to the
matching Step 3 chunk.

## Conclusion

All image URLs from `amazon_reviews_snowflake_raw_scrape.csv` are reflected
somewhere across Steps 2, 3, and 4 combined because Step 2 and Step 3 already
cover them.

However, Step 4 is still only a partial review sample and is **not** a complete
representation of the Step 3 machine-annotated review set.

## Recommended Next Fix

Generate full Step 4 review-sheet files from the Step 3 machine-annotated
outputs so that every Step 3 image row is represented in Step 4, with the
required `Approved for publishing` column added in the correct review position.
