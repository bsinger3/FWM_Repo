# Pipeline Scripts

Use these lifecycle folders for new pipeline code. Historical source-family
script folders remain during migration as compatibility wrappers where possible,
but new writes should use `pipeline_paths.py` and sibling `FWM_Data`.

Current canonical entrypoints:

- `00_raw_scrape/non_amazon/`: merchant and affiliate raw review scrapers.
- `02_qualify_for_supabase/non_amazon/`: measurement coverage, gap ranking, and
  AWIN lead qualification reports.
- `03_cv_annotate/amazon/build_supabase_image_review_package.py`: Stage 03
  review package generation for CV-annotated pending human review rows.
- `04_human_review_publish/amazon/ingest_labeled_supabase_review_workbook.py`:
  Stage 04 human-reviewed return ingest.
