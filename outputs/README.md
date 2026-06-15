# Outputs Folder Map

This folder is organized around the current Supabase image-review workflow.

## Active Folders

- `01_supabase_ready_human_approved`: rows Brianna has already manually approved and that are candidates for Supabase upload prep.
- `02_supabase_needs_human_review_cv_first_pass`: rows that have had a first pass from CV models and still need human review before production.
- `03_supabase_unprocessed_not_cv_or_human`: rows that have not yet completed the full CV gate and should not be labeled for Supabase approval yet.

## Archive

- `archive`: older generated packages, smoke tests, superseded review folders, and CV experiment outputs.

