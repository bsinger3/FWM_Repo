# Step 5 Provisional Upload Candidates Report

This report describes the provisional Step 5 upload-candidate chunk set.

Important note:

- these files are shaped like Step 5 upload files
- they are derived from the Step 4 capped measurement/person chunk set
- they do **not** enforce the final human `Approved for publishing = 1` gate yet
- they live in a separate provisional subfolder for that reason

Source rules already applied upstream in Step 4 derived data:

- `has_person = true`
- `exceeds_cap` not set
- at least one measurement present

Step 5 shaping rules applied here:

- keep only the columns present in `images_intake_sample - sampleOutput1.csv`
- preserve the sample column order exactly
- split the result into chunked CSV files

- source rows scanned: `56649`
- output rows written: `56649`
- output chunk count: `19`
- output folder: `/Users/briannasinger/Projects/FWM_Repo/data-pipelines/amazon/data/step_5_publish_ready_outputs/pre_human_approval_upload_candidates`

Step 5 output header:

- `created_at_display`
- `id`
- `original_url_display`
- `product_page_url_display`
- `monetized_product_url_display`
- `height_raw`
- `weight_raw`
- `user_comment`
- `date_review_submitted_raw`
- `height_in_display`
- `review_date`
- `source_site_display`
- `status_code`
- `fetched_at`
- `updated_at`
- `brand`
- `waist_raw_display`
- `hips_raw`
- `age_raw`
- `waist_in`
- `hips_in_display`
- `age_years_display`
- `search_fts`
- `weight_display_display`
- `weight_raw_needs_correction`
- `clothing_type_id`
- `reviewer_profile_url`
- `reviewer_name_raw`
- `inseam_inches_display`
- `color_display`
- `size_display`
- `bust_in_number_display`
- `cupsize_display`
- `weight_lbs_display`
