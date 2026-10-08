#!/usr/bin/env bash
# Start the local app with the credentials from a running MinIO container.
# The MinIO credentials are passed only through QUOTIENT_S3_* and are copied
# into AWS_* only for the individual S3 CLI subprocess in the worker.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTAINER="${QUOTIENT_MINIO_CONTAINER:-engine-minio-1}"
ENDPOINT="${QUOTIENT_S3_ENDPOINT_URL:-http://127.0.0.1:9000}"
BUCKET="${QUOTIENT_MEDIA_BUCKET:-axion-meeting-local}"

fail() {
  echo "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is required for local MinIO startup"
command -v aws >/dev/null 2>&1 || fail "aws CLI is required for local MinIO startup"
RAW_ENV="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER" 2>/dev/null)" \
  || fail "MinIO container '${CONTAINER}' is not available"

env_value() {
  local name="$1" line
  while IFS= read -r line; do
    if [[ "$line" == "${name}="* ]]; then
      printf '%s' "${line#*=}"
      return 0
    fi
  done <<<"$RAW_ENV"
  return 1
}

ACCESS_KEY="${QUOTIENT_S3_ACCESS_KEY_ID:-}"
SECRET_KEY="${QUOTIENT_S3_SECRET_ACCESS_KEY:-}"
if [[ -z "$ACCESS_KEY" ]]; then
  ACCESS_KEY="$(env_value MINIO_ROOT_USER)" \
    || fail "MinIO root access key is unavailable in '${CONTAINER}'"
fi
if [[ -z "$SECRET_KEY" ]]; then
  SECRET_KEY="$(env_value MINIO_ROOT_PASSWORD)" \
    || fail "MinIO root secret is unavailable in '${CONTAINER}'"
fi
export QUOTIENT_S3_ACCESS_KEY_ID="$ACCESS_KEY"
export QUOTIENT_S3_SECRET_ACCESS_KEY="$SECRET_KEY"
[[ -n "$QUOTIENT_S3_ACCESS_KEY_ID" && -n "$QUOTIENT_S3_SECRET_ACCESS_KEY" ]] \
  || fail "MinIO root credentials are empty in '${CONTAINER}'"

export QUOTIENT_S3_ENDPOINT_URL="$ENDPOINT"
export QUOTIENT_MEDIA_BUCKET="$BUCKET"

if ! AWS_ACCESS_KEY_ID="$ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$SECRET_KEY" \
  aws s3api head-bucket --bucket "$BUCKET" --endpoint-url "$ENDPOINT" \
    --region ap-southeast-2 --no-cli-pager >/dev/null 2>&1; then
  AWS_ACCESS_KEY_ID="$ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$SECRET_KEY" \
    aws s3api create-bucket --bucket "$BUCKET" --endpoint-url "$ENDPOINT" \
      --region ap-southeast-2 --no-cli-pager >/dev/null 2>&1 \
    || fail "could not prepare the local MinIO bucket '${BUCKET}'"
fi

exec "$ROOT/scripts/start-local.sh" "$@"
