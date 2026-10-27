#!/usr/bin/env bash
# Keep /Applications/Cytosol Viewer.app at the newest commit of origin/main.
#   scripts/mac_auto_update.sh [--force]
# Run by the launchd agent from scripts/install_auto_update.sh (every 30 min
# and at login); can also be run by hand.  Steps:
#   1. git fetch origin main in this clone (the clone itself is not touched:
#      the build happens in a separate worktree, ~/.cytosol-autoupdate/src)
#   2. stop if origin/main is the commit already installed (--force: rebuild)
#   3. build the app (build_mac.sh), run its --selftest, stop unless PASSED
#   4. wait while the app is running, then swap it into /Applications;
#      the old app goes to ~/.Trash as "Cytosol Viewer <old version>.app"
# Environment: PYTHON (python3.12 to build with; found automatically),
# MAKE_DMG=1 (also write the versioned DMG to the Desktop, make_dmg.sh).
# Log: ~/Library/Logs/CytosolViewer-autoupdate.log
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$HOME/.cytosol-autoupdate"     # no spaces: venv scripts break on them
SRC="$BASE/src"
STAMP="$BASE/installed_commit"
LOCK="$BASE/lock"
DEST="/Applications/Cytosol Viewer.app"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1
mkdir -p "$BASE"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

# launchd may start a run while the previous build is still going
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +180 2>/dev/null)" ]; then
    rmdir "$LOCK" 2>/dev/null || true; mkdir "$LOCK"
  else
    log "another update is running"; exit 0
  fi
fi
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

if [ -z "${PYTHON:-}" ]; then
  for p in "$HOME/.local/bin/python3.12" /opt/homebrew/bin/python3.12 \
           /usr/local/bin/python3.12 "$(command -v python3.12 || true)"; do
    [ -n "$p" ] && [ -x "$p" ] && { PYTHON="$p"; break; }
  done
fi
[ -n "${PYTHON:-}" ] || { log "python3.12 not found; set PYTHON"; exit 1; }
export PYTHON

git -C "$REPO" fetch --quiet origin main
NEW=$(git -C "$REPO" rev-parse origin/main)
OLD=$(cat "$STAMP" 2>/dev/null || true)
if [ "$NEW" = "$OLD" ] && [ $FORCE = 0 ] && [ -d "$DEST" ]; then
  exit 0                                   # up to date: stay quiet in the log
fi
INST=${OLD:0:7}
log "origin/main ${NEW:0:7} (installed: ${INST:-none})"

if [ ! -e "$SRC/.git" ]; then
  git -C "$REPO" worktree prune
  git -C "$REPO" worktree add --detach "$SRC" "$NEW"
else
  git -C "$SRC" checkout --quiet --force --detach "$NEW"
  git -C "$SRC" clean -fdq -e .venv
fi

log "building"
"$SRC/build_mac.sh" > "$BASE/build.log" 2>&1 || {
  log "build failed, see $BASE/build.log"; exit 1; }
APP="$SRC/dist/Cytosol Viewer.app"
VER=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' \
      "$APP/Contents/Info.plist")

log "selftest $VER"
rm -rf "$BASE/selftest"
"$APP/Contents/MacOS/Cytosol Viewer" --selftest "$BASE/selftest" \
  > "$BASE/selftest-run.log" 2>&1 || true
if ! grep -q '^PASSED$' "$BASE/selftest/selftest.log" 2>/dev/null; then
  log "selftest failed, not installing (see $BASE/selftest/selftest.log)"
  exit 1
fi

if [ "${MAKE_DMG:-0}" = 1 ]; then
  (cd "$SRC" && ./make_dmg.sh) >> "$BASE/build.log" 2>&1 \
    && log "DMG written to the Desktop" || log "DMG failed (app still installed)"
fi

# never swap the app under a running copy: wait for it to quit
waited=0
while pgrep -f "$DEST/Contents/MacOS/" > /dev/null; do
  if [ $waited = 0 ]; then
    log "Cytosol Viewer is running; installing after it quits"
    osascript -e "display notification \"$VER 빌드 완료. 앱을 종료하면 설치됩니다.\" with title \"Cytosol Viewer\"" || true
  fi
  sleep 60; waited=$((waited + 60))
  [ $waited -ge 43200 ] && { log "still running after 12 h; next run retries"; exit 0; }
done

NEWAPP="/Applications/.Cytosol Viewer.new.app"
rm -rf "$NEWAPP"
ditto "$APP" "$NEWAPP"
if [ -d "$DEST" ]; then
  OLDVER=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' \
           "$DEST/Contents/Info.plist" 2>/dev/null || echo old)
  TRASH="$HOME/.Trash/Cytosol Viewer $OLDVER.app"
  [ -e "$TRASH" ] && TRASH="$HOME/.Trash/Cytosol Viewer $OLDVER $(date +%Y%m%d-%H%M%S).app"
  mv "$DEST" "$TRASH"
fi
mv "$NEWAPP" "$DEST"
echo "$NEW" > "$STAMP"
log "installed $VER (${NEW:0:7}) to $DEST"
osascript -e "display notification \"$VER 설치됨\" with title \"Cytosol Viewer\"" || true
