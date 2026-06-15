# Deprecated Non-Amazon Pipeline Paths

This directory is retained only for transition-period compatibility wrappers and historical scrape notes.

New work should use lifecycle paths under `data-pipelines/scripts/`:

- Raw scrape: `data-pipelines/scripts/00_raw_scrape/`
- Clean/normalize: `data-pipelines/scripts/01_clean_normalize/`
- Supabase qualification: `data-pipelines/scripts/02_qualify_for_supabase/`
- CV annotation and review package generation: `data-pipelines/scripts/03_cv_annotate/`
- Human review publish: `data-pipelines/scripts/04_human_review_publish/`

Generated merchant data belongs under `../FWM_Data/00_raw_scraped_data/<merchant_or_source>/` for raw scrape output, then unified lifecycle stages after that. Amazon vs. non-Amazon should be metadata after the raw scrape stage.
