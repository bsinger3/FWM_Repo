# FWM_Data S3 Restore Handoff

This note is for the next Codex chat that needs to restore `FWM_Data` from S3 onto this machine.

## Goal

Download the full `FWM_Data` directory from the private S3 bucket to the local machine.

## Local Paths

- Repo: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Repo`
- Data directory target: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data`
- Existing raw output path inside data dir: `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data\raw\apify`

## S3 Bucket

- Bucket URL: `s3://fwm-scraping-data-briannasinger`

## AWS CLI

- Installed executable path:
  `C:\Program Files\Amazon\AWSCLIV2\aws.exe`

Important:
- `aws` may not be on `PATH` in a fresh shell.
- Prefer calling the full executable path directly.

## Current Auth Situation

At the time of this handoff:

- AWS CLI access-key credentials were configured under profile `fwm`
- region for `fwm` was set to `us-east-1`
- `aws sts get-caller-identity --profile fwm` succeeded
- the authenticated identity was `arn:aws:iam::326804802943:user/codex-sync`
- `codex-sync` has bucket-scoped access to `s3://fwm-scraping-data-briannasinger`

That means backup and restore commands should use `--profile fwm` by default.

## Credential Refresh

The `fwm` profile now uses IAM access keys, not `aws login`.

If the key is ever invalid or rotated, use an AWS admin/root session to create a new access key for IAM user `codex-sync`, then update the local `fwm` profile:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' configure --profile fwm
```

Verify with:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' sts get-caller-identity --profile fwm
```

## Restore Command

Use this exact command to restore `FWM_Data` from S3:

```powershell
& 'C:\Program Files\Amazon\AWSCLIV2\aws.exe' --profile fwm s3 sync `
  's3://fwm-scraping-data-briannasinger' `
  'C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data' `
  --exclude '.DS_Store'
```

## Expected Result

After a successful restore:

- `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Data` should contain the backed-up project data
- existing subfolders like `raw\apify` should be present or updated

## Repo Context

The repo was synced to GitHub `origin/main` and the extra temporary clone was deleted.

Only one repo folder should exist:

- `C:\Users\bsing\OneDrive\Documents\Projects\FWM\FWM_Repo`

## Useful Related Files

- [DATA.md](DATA.md)
- [AWS_BACKUP_SETUP.md](AWS_BACKUP_SETUP.md)
- [README.md](README.md)
- [scripts/sync-data-to-s3.ps1](scripts/sync-data-to-s3.ps1)
- [scripts/sync-data-to-s3.sh](scripts/sync-data-to-s3.sh)
- [scripts/create-private-s3-bucket.sh](scripts/create-private-s3-bucket.sh)

## Known Note

This machine is Windows. Prefer the Windows paths and the PowerShell sync script in this handoff note.
