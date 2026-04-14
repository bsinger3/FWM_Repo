# Amazon Data Pipeline

This folder contains the Amazon-specific data pipeline used to transform raw
scraped Amazon review image data into structured, reviewable, and eventually
publishable outputs for Friends With Measurements.

The structure here is organized around the workflow rather than around the old
`AmazonBigImages` workspace layout.


## Workflow

The approved workflow is:

1. `step_1_raw_scraping_data`
2. `step_2_standardization_and_text_extraction`
3. `step_3_image_annotation`
4. `step_4_human_review_and_visibility_decisions`
5. `step_5_publish_ready_outputs`


## Folder Structure

- `data/`
  Stores workflow-stage inputs and outputs.
- `scripts/`
  Stores step-based scripts that operate on the pipeline data.
- `docs/`
  Stores workflow references, schema references, reports, and step docs.
- `models/`
  Stores local model files used by the image-annotation workflow.


## Important Workflow Rule

Nothing belongs in Step 5 until a human has explicitly approved it for web
publishing.

The approval gate works like this:

- Step 4 review sheets must contain a column named `Approved for publishing`
- a human reviewer manually enters `1` in that column for rows approved for
  publishing on the web
- Step 5 is generated from Step 4 by:
  - keeping only rows where `Approved for publishing = 1`
  - removing rows without a `1`
  - removing the `Approved for publishing` column itself
- Step 5 files must match the `sampleOutput1` structure in
  `images_intake_sample.xlsx`
- Step 5 files must be formatted so they can be uploaded directly into DBeaver

## Step 5 Import Rule

The Step 5 source-of-truth format is the Excel workbook:

- `docs/images_intake_sample.xlsx`

In particular:

- the `sampleOutput1` sheet defines the target Step 5 column structure
- the `contraints` sheet defines field expectations and import constraints

The DBeaver import workflow reference is:

- `dbeaver_import_workflow.docx`

Important import notes from that workflow:

- import Step 5 CSVs into `images_staging`
- map the top row to `images_staging`
- set `created_at_display` to skip
- set `id` to skip
- ensure all other columns are mapped
- disable batches during import
- run the staging cleanup and insert workflow after import


## Step 4 Review Sheet Rules

Step 4 is a human-facing working review sheet, so readability matters.

- machine-generated review columns should remain human-readable
- current examples include:
  - `has_person`
  - `has_face_yunet`
  - `lighting_ok`
  - `full_lower_body_visible`
- if a machine-generated column proves unreliable, it should be removed or
  replaced rather than kept under a misleading name
- the `Approved for publishing` column should appear immediately after the
  machine-generated review columns


## Current State

This pipeline is still being reorganized from the older `AmazonBigImages`
workspace into the `FWM_Repo/data-pipelines/amazon/` structure.

That means:

- some files have already been moved into the new structure
- some scripts may still need path cleanup after migration
- Step 5 is intentionally empty until the final human approval process exists
