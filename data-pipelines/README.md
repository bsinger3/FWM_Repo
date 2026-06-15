# FWM Data Pipelines

Pipeline code is organized by lifecycle stage. Generated data lives outside the
repo in sibling `FWM_Data`; this directory should contain scripts, schemas,
docs, and temporary compatibility wrappers only.

```text
scripts/
  common/
  00_raw_scrape/
  01_clean_normalize/
  02_qualify_for_supabase/
  03_cv_annotate/
  04_human_review_publish/
schemas/
docs/
archive/
```

Current transition note: high-use legacy paths under `data-pipelines/amazon/`
and `data-pipelines/non-amazon/` are now compatibility wrappers where possible.
Canonical active script homes are under `data-pipelines/scripts/`, and new
scripts should use `data-pipelines/scripts/pipeline_paths.py` to write to the
lifecycle folders in `../FWM_Data`.
