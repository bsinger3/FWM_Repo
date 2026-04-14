# Workflow Overview

This document summarizes the Amazon pipeline workflow inside
`FWM_Repo/data-pipelines/amazon/`.

## Workflow Steps

1. `step_1_raw_scraping_data`
   Untouched raw scrape files and upstream source CSVs.
2. `step_2_standardization_and_text_extraction`
   Schema alignment plus regex/text extraction from customer comments.
3. `step_3_image_annotation`
   Computer-vision enrichment for reviewable image signals.
4. `step_4_human_review_and_visibility_decisions`
   Human review sheets, search-visibility decisions, and manual approval for
   publishing.
5. `step_5_publish_ready_outputs`
   Final exports derived only from human-approved Step 4 rows.

## Key Approval Rule

Nothing enters Step 5 until a human reviewer marks `1` in the Step 4 column
named `Approved for publishing`.

Step 5 is generated from Step 4 by:

- keeping only rows where `Approved for publishing = 1`
- removing rows where that condition is not met
- removing the `Approved for publishing` column itself
- formatting the result to match `images_intake_sample.xlsx` `sampleOutput1`
- preparing the result for direct DBeaver upload

## Step 4 Search Visibility Rule

Step 4 also determines whether an image row is eligible to appear in search
results.

The current rule is:

- all rows remain stored in the dataset
- Step 4 estimates a synthetic reviewer identity using `reviewer_profile_url`
  plus normalized `comment_text`
- rows are grouped by synthetic reviewer identity plus
  `product_page_url_display`
- no more than 3 image rows from the same reviewer-product group should remain
  search-eligible
- overflow rows are marked with `exceeds_cap = 1`
- rows marked `exceeds_cap = 1` are still retained, but should not be returned
  in search results
- when choosing which rows remain inside the cap, prefer rows with
  `has_face_yunet = true`
