#!/usr/bin/env bash
# Build "Cytosol Viewer.app" into dist/ on macOS.
#   ./build_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  "$PY" -m venv .venv
fi
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller

pyinstaller --noconfirm --clean cytosol_viewer.spec

echo
echo "Built: $(pwd)/dist/Cytosol Viewer.app"
