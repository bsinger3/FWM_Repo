# FWM_Data S3 Restore Handoff

This note is for the next Codex chat that needs to restore `FWM_Data` from S3 onto this machine.

## Goal

Download the full `FWM_Data` directory from the private S3 bucket to the local machine.

## Local Paths

- Repo: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Repo`
- Data directory target: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data`
- Existing raw output path inside data dir: `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data\raw\apify`

## S3 Bucket

- Bucket URL: `s3://fwm-scraping-data-briannasinger`

## AWS CLI

- Installed executable path:
  `C:\Program Files\Amazon\AWSCLIV2\aws.exe`

Important:
- `aws` may not be on `PATH` in a fresh shell.
- Prefer calling the full executable path directly.

## Current Auth Situation

At the time of this handoff, AWS CLI was installed but `aws sts get-caller-identity` failed with:

- `NoCredentials: Unable to locate credentials`

So the next Codex chat should first check whether the user is already logged in on this machine.

## Login Command

If not logged in, ask the user to run:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' login
```

After login completes, verify with:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' sts get-caller-identity
```

## Restore Command

Use this exact command to restore `FWM_Data` from S3:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' s3 sync `
  's3://fwm-scraping-data-briannasinger' `
  'C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data' `
  --exclude '.DS_Store'
```

## Expected Result

After a successful restore:

- `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Data` should contain the backed-up project data
- existing subfolders like `raw\apify` should be present or updated

## Repo Context

The repo was synced to GitHub `origin/main` and the extra temporary clone was deleted.

Only one repo folder should exist:

- `C:\Users\bsing\OneDrive\Documents\Projects\FWM_Repo`

## Useful Related Files

- [DATA.md](C:\Users\bsing\OneDrive\Documents\Projects\FWM_Repo\DATA.md)
- [README.md](C:\Users\bsing\OneDrive\Documents\Projects\FWM_Repo\README.md)
- [scripts/sync-data-to-s3.sh](C:\Users\bsing\OneDrive\Documents\Projects\FWM_Repo\scripts\sync-data-to-s3.sh)
- [scripts/create-private-s3-bucket.sh](C:\Users\bsing\OneDrive\Documents\Projects\FWM_Repo\scripts\create-private-s3-bucket.sh)

## Known Note

This machine is Windows, while some repo docs still show older macOS-style paths like `/Users/briannasinger/Projects/FWM_Data`. For this machine, use the Windows paths in this handoff note.
