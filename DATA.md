# FWM Data Storage

This repo should stay small enough to push to GitHub. Keep source code, docs, schema, and app files in `FWM_Repo`; keep scraped data and generated pipeline outputs outside the repo.

## What Stays In Git

- App files such as `index.html`, `config.js`, and static pages.
- Supabase migrations and schema files.
- Pipeline scripts in `data-pipelines/**/scripts/`.
- Lightweight pipeline docs in `data-pipelines/**/docs/`.

## What Stays Out Of Git

- Raw scraped CSVs and downloaded source files.
- Intermediate review batches and generated exports.
- Publish-ready output files that can be regenerated or backed up elsewhere.
- Local ML model files such as `.pt`, `.onnx`, and `.caffemodel`.
- Local cache/vendor folders.

## Local Data Directory

Use this sibling directory for local scraping work:

```text
Mac:     /Users/briannasinger/Projects/FWM/FWM_Data
Windows: C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data
```

Recommended layout:

```text
FWM_Data/
  amazon/
    data/
    models/
  non-amazon/
    data/
  models/
```

The repo can keep local symlinks at `data-pipelines/amazon/data`, `data-pipelines/amazon/models`, and `data-pipelines/non-amazon/data` so existing scripts can still use their current paths while the real files live in `FWM_Data`.

For new retailer scrapes, follow [new-scrape-rules.md](new-scrape-rules.md).
Every scrape handoff should report how many rows have a product URL, at least
one measurement, a customer image, the ordered size, and how many rows satisfy
all four requirements for Supabase insertion.

## S3 Backup

Copy `.env.example` to `.env`, then set these values:

```text
FWM_DATA_DIR=C:/Users/bsing/OneDrive/Documents/Projects/FWM/FWM_Data
FWM_S3_BUCKET=s3://fwm-scraping-data-briannasinger
FWM_AWS_PROFILE=fwm
```

On Mac, use:

```text
FWM_DATA_DIR=/Users/briannasinger/Projects/FWM/FWM_Data
```

Use the dedicated AWS CLI profile `fwm`. On this Windows machine, `fwm` is configured with access keys for the IAM user `codex-sync`, not root login credentials.

Verify the active identity:

```powershell
aws sts get-caller-identity --profile fwm
```

Expected identity:

```text
arn:aws:iam::326804802943:user/codex-sync
```

After an AWS bucket exists, back up the local data directory with:

```powershell
.\scripts\sync-data-to-s3.ps1
```

On Git Bash or WSL, you can also use:

```bash
scripts/sync-data-to-s3.sh
```

Restore with:

```powershell
aws --profile fwm s3 sync s3://fwm-scraping-data-briannasinger C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data --exclude ".DS_Store"
```

Use a private bucket. Do not put scraped data in a public bucket unless you have deliberately reviewed the privacy and licensing implications.

Current note:

- The `fwm` profile authenticates as IAM user `codex-sync`.
- `codex-sync` has bucket-scoped S3 permissions for `s3://fwm-scraping-data-briannasinger`.
- Do not use AWS root credentials for normal backup or restore work.

## Creating The Bucket

After AWS CLI login is configured, create a private encrypted bucket:

```bash
scripts/create-private-s3-bucket.sh YOUR_GLOBALLY_UNIQUE_BUCKET_NAME us-east-1
```

Then update `.env`:

```text
FWM_S3_BUCKET=s3://YOUR_GLOBALLY_UNIQUE_BUCKET_NAME
```

See [AWS_BACKUP_SETUP.md](AWS_BACKUP_SETUP.md) for the current Windows-specific login, backup, and restore workflow.
