#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  pwd
)"

AWS_REGION="${AWS_REGION:-ap-northeast-1}"
FUNCTION_NAME="${PUBLISHER_FUNCTION_NAME:-KendoKeikoPublisher}"
FROM_DATE="${FROM_DATE:-$(TZ=Asia/Tokyo date +%F)}"
ORGANIZATION_ID=""
EXPECTED_COUNT=""
DRY_RUN=false

usage() {
  cat <<'EOF'
Usage:
  scripts/publish_manual_events.sh [options]

Options:
  --organization-id ID  Verify the public event count for this organization.
  --expected-count N     Expected active event count on or after --from-date.
  --from-date YYYY-MM-DD Publication start date. Default: today in JST.
  --dry-run              Validate, test, and build without updating AWS.
  -h, --help             Show this help.

Environment variables:
  AWS_REGION              Default: ap-northeast-1
  PUBLISHER_FUNCTION_NAME Default: KendoKeikoPublisher
EOF
}

fail() {
  echo "[ERROR] $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

while (($#)); do
  case "$1" in
    --organization-id)
      (($# >= 2)) || fail "--organization-id requires a value"
      ORGANIZATION_ID="$2"
      shift 2
      ;;
    --expected-count)
      (($# >= 2)) || fail "--expected-count requires a value"
      EXPECTED_COUNT="$2"
      shift 2
      ;;
    --from-date)
      (($# >= 2)) || fail "--from-date requires a value"
      FROM_DATE="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown option: $1"
      ;;
  esac
done

if [[ -n "${ORGANIZATION_ID}" && -z "${EXPECTED_COUNT}" ]] || \
   [[ -z "${ORGANIZATION_ID}" && -n "${EXPECTED_COUNT}" ]]; then
  fail "--organization-id and --expected-count must be specified together"
fi
if [[ -n "${EXPECTED_COUNT}" && ! "${EXPECTED_COUNT}" =~ ^[0-9]+$ ]]; then
  fail "--expected-count must be a non-negative integer"
fi

require_command python
require_command git
require_command jq
require_command unzip
require_command cmp

cd "${ROOT_DIR}"

echo "[INFO] repository: ${ROOT_DIR}"
echo "[INFO] region: ${AWS_REGION}"
echo "[INFO] from date: ${FROM_DATE}"
echo "[INFO] publisher function: ${FUNCTION_NAME}"
if [[ -n "${ORGANIZATION_ID}" ]]; then
  echo "[INFO] organization check: ${ORGANIZATION_ID} (${EXPECTED_COUNT} events expected)"
fi
if ${DRY_RUN}; then
  echo "[INFO] mode: dry-run (AWS update and publish are skipped)"
else
  echo "[INFO] mode: publish"
fi

if ! ${DRY_RUN}; then
  current_branch="$(git branch --show-current)"
  [[ "${current_branch}" == "main" ]] || fail "production publishing must run from main (current: ${current_branch:-detached})"

  if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    git status --short
    fail "tracked files must be clean before production publishing"
  fi

  upstream_ref="$(git rev-parse --abbrev-ref '@{upstream}' 2>/dev/null || true)"
  [[ -n "${upstream_ref}" ]] || fail "main has no upstream branch"
  [[ "$(git rev-parse HEAD)" == "$(git rev-parse '@{upstream}')" ]] || \
    fail "main does not match ${upstream_ref}; pull or push before publishing"
fi

echo "[INFO] validate organizations and manual events"
python - "${FROM_DATE}" "${ORGANIZATION_ID}" "${EXPECTED_COUNT}" <<'PY'
from __future__ import annotations

import datetime as dt
import sys

from kendo_keiko.manual_events import load_manual_events
from kendo_keiko.repository import load_organizations

from_date_raw, organization_id, expected_count_raw = sys.argv[1:4]
from_date = dt.date.fromisoformat(from_date_raw)
organizations = load_organizations()
manual_events = load_manual_events()

organization_ids = [organization.organization_id for organization in organizations]
if len(organization_ids) != len(set(organization_ids)):
    raise ValueError("duplicate organization_id found in organizations.json")

known_ids = set(organization_ids)
unknown_ids = sorted(
    {
        str(event["organization_id"])
        for event in manual_events
        if event["organization_id"] not in known_ids
    }
)
if unknown_ids:
    raise ValueError(
        "manual event references unknown organization_id: "
        + ", ".join(unknown_ids)
    )

print(
    f"[INFO] organizations={len(organizations)} "
    f"manual_events={len(manual_events)}"
)

if organization_id:
    if organization_id not in known_ids:
        raise ValueError(f"organization_id not found: {organization_id}")
    expected_count = int(expected_count_raw)
    actual_count = sum(
        1
        for event in manual_events
        if event["organization_id"] == organization_id
        and event["status"] == "active"
        and dt.date.fromisoformat(event["event_date"]) >= from_date
    )
    print(
        f"[INFO] local active events: organization_id={organization_id} "
        f"count={actual_count}"
    )
    if actual_count != expected_count:
        raise ValueError(
            f"local event count mismatch for {organization_id}: "
            f"expected={expected_count} actual={actual_count}"
        )
PY

echo "[INFO] verify generated organization section is current"
index_backup="$(mktemp)"
cp public/index.html "${index_backup}"
python scripts/generate_organization_section.py
if ! cmp -s public/index.html "${index_backup}"; then
  cp "${index_backup}" public/index.html
  rm -f "${index_backup}"
  fail "public/index.html is stale; run scripts/generate_organization_section.py and commit the result"
fi
rm -f "${index_backup}"

echo "[INFO] run tests"
python -m unittest discover -s tests -v

echo "[INFO] build Lambda ZIP"
bash scripts/build_lambda.sh

ZIP_PATH="${ROOT_DIR}/lambda_function.zip"
[[ -f "${ZIP_PATH}" ]] || fail "Lambda ZIP not found: ${ZIP_PATH}"

echo "[INFO] verify data files inside Lambda ZIP"
unzip -p "${ZIP_PATH}" data/organizations.json | jq -e 'type == "array"' >/dev/null
unzip -p "${ZIP_PATH}" data/manual_events.json \
  | jq -e '.schema_version == "manual-events-0.1" and (.events | type == "array")' \
  >/dev/null

if [[ -n "${ORGANIZATION_ID}" ]]; then
  unzip -p "${ZIP_PATH}" data/organizations.json \
    | jq -e --arg organization_id "${ORGANIZATION_ID}" \
        'any(.[]; .organization_id == $organization_id)' \
    >/dev/null

  zip_count="$({
    unzip -p "${ZIP_PATH}" data/manual_events.json
  } | jq \
    --arg organization_id "${ORGANIZATION_ID}" \
    --arg from_date "${FROM_DATE}" \
    '[.events[]
      | select(
          .organization_id == $organization_id
          and .status == "active"
          and .event_date >= $from_date
        )
    ] | length')"
  [[ "${zip_count}" == "${EXPECTED_COUNT}" ]] || \
    fail "ZIP event count mismatch: expected=${EXPECTED_COUNT} actual=${zip_count}"
  echo "[INFO] ZIP active events: organization_id=${ORGANIZATION_ID} count=${zip_count}"
fi

if ${DRY_RUN}; then
  echo "[INFO] dry-run completed successfully"
  exit 0
fi

require_command aws
require_command openssl

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT

identity_file="${work_dir}/identity.json"
config_file="${work_dir}/publisher-config.json"
update_file="${work_dir}/publisher-update.json"
invoke_meta_file="${work_dir}/publisher-invoke-meta.json"
response_file="${work_dir}/publisher-response.json"
events_file="${work_dir}/events.json"

echo "[INFO] confirm AWS account"
aws sts get-caller-identity --region "${AWS_REGION}" > "${identity_file}"
jq '{Account,Arn}' "${identity_file}"

echo "[INFO] read Publisher configuration"
aws lambda get-function-configuration \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  > "${config_file}"
jq '{FunctionName,FunctionArn,Runtime,Handler,LastUpdateStatus,Environment:.Environment.Variables}' "${config_file}"

EVENTS_BUCKET="$(jq -r '.Environment.Variables.EVENTS_BUCKET // empty' "${config_file}")"
EVENTS_KEY="$(jq -r '.Environment.Variables.EVENTS_KEY // "events.json"' "${config_file}")"
INDEX_KEY="$(jq -r '.Environment.Variables.INDEX_KEY // "index.html"' "${config_file}")"
SITEMAP_KEY="$(jq -r '.Environment.Variables.SITEMAP_KEY // "sitemap.xml"' "${config_file}")"
TABLE_NAME="$(jq -r '.Environment.Variables.TABLE_NAME // "KendoKeikoEvents"' "${config_file}")"
SITE_URL="$(jq -r '.Environment.Variables.SITE_URL // "https://kendo-keiko.com/"' "${config_file}")"
[[ -n "${EVENTS_BUCKET}" ]] || fail "Publisher environment variable EVENTS_BUCKET is not set"

local_code_sha="$(openssl dgst -sha256 -binary "${ZIP_PATH}" | openssl base64 -A)"
echo "[INFO] local Lambda CodeSha256: ${local_code_sha}"

echo "[INFO] update ${FUNCTION_NAME} only"
aws lambda update-function-code \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --zip-file "fileb://${ZIP_PATH}" \
  > "${update_file}"

aws lambda wait function-updated \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}"

remote_code_sha="$({
  aws lambda get-function-configuration \
    --function-name "${FUNCTION_NAME}" \
    --region "${AWS_REGION}"
} | jq -r '.CodeSha256')"
[[ "${remote_code_sha}" == "${local_code_sha}" ]] || \
  fail "Lambda CodeSha256 mismatch: local=${local_code_sha} remote=${remote_code_sha}"
echo "[INFO] Lambda code hash verified"

payload="$({
  jq -nc \
    --arg region "${AWS_REGION}" \
    --arg table_name "${TABLE_NAME}" \
    --arg from_date "${FROM_DATE}" \
    --arg events_bucket "${EVENTS_BUCKET}" \
    --arg events_key "${EVENTS_KEY}" \
    --arg index_key "${INDEX_KEY}" \
    --arg sitemap_key "${SITEMAP_KEY}" \
    --arg site_url "${SITE_URL}" \
    '{
      publish_only: true,
      publish_to_s3: true,
      publish_index_html: true,
      region: $region,
      table_name: $table_name,
      from_date: $from_date,
      events_bucket: $events_bucket,
      events_key: $events_key,
      index_key: $index_key,
      sitemap_key: $sitemap_key,
      site_url: $site_url
    }'
})"

echo "[INFO] invoke Publisher in publish_only mode"
aws lambda invoke \
  --function-name "${FUNCTION_NAME}" \
  --region "${AWS_REGION}" \
  --cli-binary-format raw-in-base64-out \
  --payload "${payload}" \
  "${response_file}" \
  > "${invoke_meta_file}"

jq . "${invoke_meta_file}"
jq . "${response_file}"

function_error="$(jq -r '.FunctionError // empty' "${invoke_meta_file}")"
[[ -z "${function_error}" ]] || fail "Publisher returned FunctionError: ${function_error}"
[[ "$(jq -r '.StatusCode' "${invoke_meta_file}")" == "200" ]] || \
  fail "Publisher invocation did not return StatusCode 200"

jq -e '
  .mode == "publish_only"
  and .s3_published == true
  and .index_published == true
  and .sitemap_published == true
' "${response_file}" >/dev/null || fail "Publisher response flags are invalid"

echo "[INFO] verify S3 source object: s3://${EVENTS_BUCKET}/${EVENTS_KEY}"
aws s3 cp \
  "s3://${EVENTS_BUCKET}/${EVENTS_KEY}" \
  "${events_file}" \
  --region "${AWS_REGION}" \
  --only-show-errors

jq -e '
  (.events | type == "array")
  and (.event_count == (.events | length))
  and ([.events[]
    | select(
        has("update_mode") == false
        or has("participation_type") == false
        or has("verified_at") == false
        or has("review_due_at") == false
      )
    ] | length == 0)
' "${events_file}" >/dev/null || fail "S3 events.json validation failed"

if [[ -n "${ORGANIZATION_ID}" ]]; then
  published_count="$(jq \
    --arg organization_id "${ORGANIZATION_ID}" \
    '[.events[] | select(.organization_id == $organization_id)] | length' \
    "${events_file}")"
  [[ "${published_count}" == "${EXPECTED_COUNT}" ]] || \
    fail "published event count mismatch: expected=${EXPECTED_COUNT} actual=${published_count}"
  echo "[INFO] published events: organization_id=${ORGANIZATION_ID} count=${published_count}"
fi

echo "[INFO] publish completed successfully"
echo "[INFO] S3 updated: ${EVENTS_KEY}, ${INDEX_KEY}, ${SITEMAP_KEY}, and public assets"
echo "[INFO] CloudFront may serve the previous index.html until its cache expires"
