#!/usr/bin/env bash
set -euo pipefail

BUCKET_NAME="${1:-}"
REGION="${2:-us-east-1}"

if ! command -v aws >/dev/null 2>&1; then
  echo "AWS CLI is not installed. Install it first, then run this script again." >&2
  exit 1
fi

if [[ -z "${BUCKET_NAME}" ]]; then
  echo "Usage: scripts/create-private-s3-bucket.sh BUCKET_NAME [REGION]" >&2
  exit 1
fi

if [[ "${REGION}" == "us-east-1" ]]; then
  aws s3api create-bucket --bucket "${BUCKET_NAME}" --region "${REGION}"
else
  aws s3api create-bucket \
    --bucket "${BUCKET_NAME}" \
    --region "${REGION}" \
    --create-bucket-configuration "LocationConstraint=${REGION}"
fi

aws s3api put-public-access-block \
  --bucket "${BUCKET_NAME}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
  --bucket "${BUCKET_NAME}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-versioning \
  --bucket "${BUCKET_NAME}" \
  --versioning-configuration Status=Enabled

echo "Created private encrypted bucket: s3://${BUCKET_NAME}"
