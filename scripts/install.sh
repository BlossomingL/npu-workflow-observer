#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python -m venv "$ROOT/.venv"
source "$ROOT/.venv/bin/activate"
python -m pip install -e "$ROOT" --no-build-isolation
cat <<MSG
Installed.
Activate with:
  source "$ROOT/.venv/bin/activate"
Then start:
  npu-observer daemon
MSG
