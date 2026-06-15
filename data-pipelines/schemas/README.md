# Pipeline Schemas

This folder is for lightweight schema documentation for the lifecycle pipeline
stages. Store generated datasets in `../FWM_Data`, not here.

Stage contracts:

- `00_raw_scraped_data`: source-specific scraper outputs and scrape manifests.
- `01_cleaned_normalized_data`: standardized columns, normalized URLs,
  source metadata, parsed measurements, and deduped rows where appropriate.
- `02_supabase_qualified_data`: rows with image, product URL, and at least one
  measurement.
- `03_cv_annotated_pending_human_review`: Supabase-qualified rows enriched with
  `review_id`, CV annotations, crop metadata, and review packages.
- `04_human_reviewed_ready_to_publish`: human-approved rows ready for publish.
