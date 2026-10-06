#!/usr/bin/env bash
set -euo pipefail

# This entrypoint is intentionally independent of an interactive shell.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${REEL_PYTHON:-${ROOT_DIR}/.venv-reel/bin/python}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "[CONFIG] Reel venv is missing: ${PYTHON_BIN}" >&2
  echo "Create it with: ${ROOT_DIR}/.venv/bin/python -m venv ${ROOT_DIR}/.venv-reel" >&2
  echo "Then install: ${PYTHON_BIN} -m pip install -r ${ROOT_DIR}/requirements-story.txt" >&2
  exit 5
fi

cd "${ROOT_DIR}"
exec "${PYTHON_BIN}" "${ROOT_DIR}/scripts/generate_instagram_reel.py" "$@"
