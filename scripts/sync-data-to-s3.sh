#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

if ! command -v aws >/dev/null 2>&1; then
  echo "AWS CLI is not installed. Install it first, then run this script again." >&2
  exit 1
fi

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi

FWM_DATA_DIR="${FWM_DATA_DIR:-/Users/briannasinger/Projects/FWM_Data}"
FWM_S3_BUCKET="${FWM_S3_BUCKET:-}"

if [[ -z "${FWM_S3_BUCKET}" || "${FWM_S3_BUCKET}" == "s3://your-private-fwm-data-bucket" ]]; then
  echo "Set FWM_S3_BUCKET in ${ENV_FILE} before syncing." >&2
  exit 1
fi

if [[ ! -d "${FWM_DATA_DIR}" ]]; then
  echo "Data directory does not exist: ${FWM_DATA_DIR}" >&2
  exit 1
fi

aws s3 sync "${FWM_DATA_DIR}" "${FWM_S3_BUCKET}" \
  --exclude ".DS_Store" \
  --exclude "**/.DS_Store"
