# FWM Data Storage

This repo should stay lightweight. Keep source code, docs, schemas, migrations,
tests, and small manifests in `FWM_Repo`; keep scraped data and generated
pipeline artifacts in the sibling `FWM_Data` directory.

## What Stays In Git

- App files, scripts, schemas, migrations, and tests.
- Lightweight pipeline docs and runbooks.
- Small manifests that explain where generated data lives.

## What Stays Out Of Git

- Raw scraped CSVs, JSONL files, downloaded images, and source workbooks.
- Intermediate review packages, CV outputs, mobile review bundles, and returns.
- Publish-ready exports that are backed up through `FWM_Data` and S3.
- Local ML model weights and downloaded model/cache assets.
- Codex transcript JSON files after they have been verified in Supabase.

## Local Data Directory

Use this sibling directory for local scraping and generated data:

```text
Mac:     /Users/briannasinger/Projects/FWM/FWM_Data
Windows: C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data
```

Canonical layout:

```text
FWM_Data/
  00_raw_scraped_data/
    <merchant_or_source>/
      <run_id>/
        raw_reviews.csv
        raw_products.csv
        images/
        scrape_manifest.json
        run_log.txt
  01_cleaned_normalized_data/
  02_supabase_qualified_data/
  03_cv_annotated_pending_human_review/
  04_human_reviewed_ready_to_publish/
  _reports/
  _archive/
    old_outputs/
    old_review_bundles/
    old_cv_experiments/
    transcripts/
    deprecated_scrape_runs/
```

`00_raw_scraped_data` is the only stage organized primarily by merchant/source.
After raw scrape, Amazon vs non-Amazon should be metadata such as
`source_family`, `source_site_display`, or retailer/source columns rather than
top-level lifecycle folders.

Stage meanings:

- `00_raw_scraped_data`: raw scraper outputs, source-specific and messy.
- `01_cleaned_normalized_data`: unified rows with standard columns, normalized
  product/image URLs, parsed measurements, retailer/source metadata, and
  deduping where appropriate.
- `02_supabase_qualified_data`: candidate rows with at least image, product URL,
  and one measurement.
- `03_cv_annotated_pending_human_review`: Supabase-qualified rows with
  image-level CV annotations, stable `review_id`, crop metadata, future image
  annotation fields, and review package generation. These rows are not yet human
  reviewed.
- `04_human_reviewed_ready_to_publish`: human-approved rows ready for Supabase
  or production publishing.

## Transcript Artifacts

Codex transcript JSON files belong in Supabase table `codex_chat_transcripts`.
Before removing a local transcript file, verify the corresponding row exists in
Supabase with the expected `chat_key`, `message_count`, timing, and summary
metadata. Temporary or archival local copies belong under
`FWM_Data/_archive/transcripts/`, not in the repo root.

## S3 Backup

S3 is the remote disaster backup for the local `FWM_Data` tree. It is not the
only archive; local archive folders under `FWM_Data/_archive/` should exist
before syncing.

Copy `.env.example` to `.env`, then set:

```text
FWM_DATA_DIR=/Users/briannasinger/Projects/FWM/FWM_Data
FWM_S3_BUCKET=s3://fwm-scraping-data-briannasinger
FWM_AWS_PROFILE=fwm
```

Verify the active identity:

```bash
aws sts get-caller-identity --profile "$FWM_AWS_PROFILE"
```

Back up the local data directory:

```bash
scripts/sync-data-to-s3.sh
```

On this Mac, `FWM_AWS_PROFILE=default` has previously been the working profile.
Confirm the identity before using it.
