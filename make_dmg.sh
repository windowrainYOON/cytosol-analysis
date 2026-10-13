#!/usr/bin/env bash
# Package dist/Cytosol Viewer.app into a drag-to-install DMG.
#   ./make_dmg.sh [output.dmg]
# default: ~/Desktop/CytosolViewer-<version>-<commit>.dmg (see scripts/build_name.sh)
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/Cytosol Viewer.app"
OUT="${1:-$HOME/Desktop/$(./scripts/build_name.sh).dmg}"
[ -d "$APP" ] || { echo "missing $APP; run ./build_mac.sh first" >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

rm -f "$OUT"
hdiutil create -volname "Cytosol Viewer" -srcfolder "$STAGE" -ov -format UDZO "$OUT"
echo "Built: $OUT"
