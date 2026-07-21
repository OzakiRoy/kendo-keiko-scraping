#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  pwd
)"

BUILD_DIR="${ROOT_DIR}/build/lambda"
ZIP_PATH="${ROOT_DIR}/lambda_function.zip"

echo "[INFO] clean build directory"
rm -rf "${BUILD_DIR}" "${ZIP_PATH}"

mkdir -p "${BUILD_DIR}/data" "${BUILD_DIR}/public"

echo "[INFO] install dependencies"
python -m pip install \
  --requirement "${ROOT_DIR}/requirements.txt" \
  --target "${BUILD_DIR}" \
  --quiet

# charset-normalizer の mypyc 拡張はビルド時のPythonマイナーバージョンに
# 依存する。純Python実装も同梱されているため、Lambda Python 3.12との
# 互換性を保つ目的で任意の高速化バイナリだけを除去する。
find "${BUILD_DIR}" -type f \
  \( -path '*/charset_normalizer/*.so' -o -name '*__mypyc*.so' \) \
  -delete

echo "[INFO] copy application files"
cp \
  "${ROOT_DIR}/export_events.py" \
  "${ROOT_DIR}/scrape_kendo_schedule.py" \
  "${ROOT_DIR}/lambda_function.py" \
  "${BUILD_DIR}/"

cp -R \
  "${ROOT_DIR}/kendo_keiko" \
  "${BUILD_DIR}/kendo_keiko"

cp \
  "${ROOT_DIR}/data/organizations.json" \
  "${BUILD_DIR}/data/organizations.json"

cp \
  "${ROOT_DIR}/public/index.html" \
  "${BUILD_DIR}/public/index.html"

echo "[INFO] remove Python cache files"
find "${BUILD_DIR}" \
  -type d \
  -name '__pycache__' \
  -prune \
  -exec rm -rf {} +

find "${BUILD_DIR}" \
  -type f \
  \( -name '*.pyc' -o -name '*.pyo' \) \
  -delete

echo "[INFO] test imports from build directory"
(
  cd /tmp

  PYTHONPATH="${BUILD_DIR}" python - <<'PY'
import lambda_function
from kendo_keiko.models import RawScrapedEvent
from kendo_keiko.scrapers.ajkf import scrape

print("[INFO] Lambda package imports: OK")
PY
)

echo "[INFO] remove cache files created by import test"
find "${BUILD_DIR}" \
  -type d \
  -name '__pycache__' \
  -prune \
  -exec rm -rf {} +

find "${BUILD_DIR}" \
  -type f \
  \( -name '*.pyc' -o -name '*.pyo' \) \
  -delete

echo "[INFO] create ZIP package"
(
  cd "${BUILD_DIR}"
  zip -qr "${ZIP_PATH}" .
)

echo "[INFO] verify ZIP contents"
required_files=(
  "lambda_function.py"
  "export_events.py"
  "scrape_kendo_schedule.py"
  "kendo_keiko/__init__.py"
  "kendo_keiko/models.py"
  "kendo_keiko/pipeline.py"
  "kendo_keiko/static_site.py"
  "kendo_keiko/scrapers/__init__.py"
  "kendo_keiko/scrapers/ajkf.py"
  "kendo_keiko/scrapers/common.py"
  "kendo_keiko/scrapers/kent.py"
  "kendo_keiko/scrapers/kanagawa.py"
  "kendo_keiko/scrapers/kenkyukai.py"
  "kendo_keiko/scrapers/kenbokukai.py"
  "kendo_keiko/scrapers/tokyo.py"
  "data/organizations.json"
  "public/index.html"
)

ZIP_CONTENTS_FILE="$(mktemp)"
trap 'rm -f "${ZIP_CONTENTS_FILE}"' EXIT

unzip -Z1 "${ZIP_PATH}" > "${ZIP_CONTENTS_FILE}"

for required_file in "${required_files[@]}"; do
  if ! grep -Fxq "${required_file}" "${ZIP_CONTENTS_FILE}"; then
    echo "[ERROR] missing from ZIP: ${required_file}" >&2
    exit 1
  fi
done

if grep -Eq '\.(pyc|pyo)$' "${ZIP_CONTENTS_FILE}"; then
  echo "[ERROR] Python cache file found in ZIP" >&2
  grep -E '\.(pyc|pyo)$' "${ZIP_CONTENTS_FILE}" >&2
  exit 1
fi

echo "[INFO] created: ${ZIP_PATH}"
ls -lh "${ZIP_PATH}"
