# AWS Backup Setup

This document records the current S3 backup setup for `FWM_Data` on the Mac and Windows machines. S3 is disaster/remote backup for the local lifecycle data tree; keep local archive folders under `FWM_Data/_archive/` before syncing.

## Current Setup

- Mac repo path: `/Users/briannasinger/Projects/FWM/FWM_Repo`
- Mac data path: `/Users/briannasinger/Projects/FWM/FWM_Data`
- Windows repo path: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Repo`
- Windows data path: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data`
- S3 bucket: `s3://fwm-scraping-data-briannasinger`
- AWS CLI profile: `fwm`
- AWS region: `us-east-1`

## Local Config

The repo-local `.env` is expected to contain:

```text
FWM_DATA_DIR=C:/Users/bsing/OneDrive/Documents/Projects/FWM/FWM_Data
FWM_S3_BUCKET=s3://fwm-scraping-data-briannasinger
FWM_AWS_PROFILE=fwm
```

On Mac, set `FWM_DATA_DIR=/Users/briannasinger/Projects/FWM/FWM_Data`.

## Scripts

The backup workflow now has two sync helpers:

- Windows PowerShell: `scripts/sync-data-to-s3.ps1`
- Bash: `scripts/sync-data-to-s3.sh`

Both scripts now default to the dedicated AWS profile `fwm`.

## Auth Workflow

Use the dedicated AWS profile `fwm` instead of overwriting `default`.

The `fwm` profile is configured with access keys for the IAM user `codex-sync`, not with root login credentials.

If this profile ever stops working, create or rotate an access key for `codex-sync` from an admin/root AWS session, then update the local `fwm` profile. Do not put root credentials into the backup profile.

Verification command:

```powershell
aws sts get-caller-identity --profile fwm
```

## Current Verified Auth State

AWS auth was verified successfully with:

```powershell
aws sts get-caller-identity --profile fwm
```

The returned identity was:

```text
arn:aws:iam::326804802943:user/codex-sync
```

That means the profile is working and is no longer authenticated as the AWS root identity.

## IAM Permissions

The `codex-sync` user has a bucket-scoped inline policy named:

```text
FWMDataBucketSyncPolicy
```

It allows list/read/write/delete operations only for:

```text
s3://fwm-scraping-data-briannasinger
```

The previous broad `AmazonS3FullAccess` managed policy was detached from `codex-sync`.

## Backup Command

Recommended Windows command:

```powershell
.\scripts\sync-data-to-s3.ps1
```

The script reads `.env`, uses the `fwm` profile, and syncs `FWM_Data` to the S3 bucket.

## Restore Command

```powershell
aws --profile fwm s3 sync s3://fwm-scraping-data-briannasinger C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data --exclude ".DS_Store"
```

## What Changed In This Round

- Set the repo-local S3 bucket target to `s3://fwm-scraping-data-briannasinger`
- Added `FWM_AWS_PROFILE=fwm` to the repo-local config
- Added a Windows-native sync helper: `scripts/sync-data-to-s3.ps1`
- Updated the existing bash sync helper to use the `fwm` profile
- Set the `fwm` profile region to `us-east-1`
- Reconfigured the `fwm` profile to use IAM user `codex-sync`
- Replaced broad S3 permissions with a bucket-scoped inline policy
- Verified backup and restore access from the CLI
