$ErrorActionPreference = "Stop"

$rootDir = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $rootDir ".env"

if (-not (Get-Command aws -ErrorAction SilentlyContinue)) {
    throw "AWS CLI is not installed. Install it first, then run this script again."
}

if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*#' -or $_ -notmatch '=') {
            return
        }

        $parts = $_ -split '=', 2
        $name = $parts[0].Trim()
        $value = $parts[1].Trim()
        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$fwmDataDir = if ($env:FWM_DATA_DIR) { $env:FWM_DATA_DIR } else { "C:/Users/bsing/OneDrive/Documents/Projects/FWM_Data" }
$fwmS3Bucket = $env:FWM_S3_BUCKET
$fwmAwsProfile = if ($env:FWM_AWS_PROFILE) { $env:FWM_AWS_PROFILE } else { "fwm" }

if (-not $fwmS3Bucket -or $fwmS3Bucket -eq "s3://your-private-fwm-data-bucket") {
    throw "Set FWM_S3_BUCKET in $envFile before syncing."
}

if (-not (Test-Path $fwmDataDir)) {
    throw "Data directory does not exist: $fwmDataDir"
}

aws --profile $fwmAwsProfile s3 sync $fwmDataDir $fwmS3Bucket --exclude ".DS_Store" --exclude "**/.DS_Store"
