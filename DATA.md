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
/Users/briannasinger/Projects/FWM_Data/
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

## S3 Backup

Copy `.env.example` to `.env`, then set `FWM_S3_BUCKET` to the private bucket URL.

After an AWS bucket exists, back up the local data directory with:

```bash
scripts/sync-data-to-s3.sh
```

Restore with:

```bash
aws s3 sync s3://YOUR_BUCKET_NAME /Users/briannasinger/Projects/FWM_Data --exclude ".DS_Store"
```

Use a private bucket. Do not put scraped data in a public bucket unless you have deliberately reviewed the privacy and licensing implications.

## Creating The Bucket

After AWS CLI login is configured, create a private encrypted bucket:

```bash
scripts/create-private-s3-bucket.sh YOUR_GLOBALLY_UNIQUE_BUCKET_NAME us-east-1
```

Then update `.env`:

```text
FWM_S3_BUCKET=s3://YOUR_GLOBALLY_UNIQUE_BUCKET_NAME
```
