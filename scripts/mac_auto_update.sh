#!/usr/bin/env bash
# Keep /Applications/Cytosol Viewer.app at the newest commit of origin/main.
#   scripts/mac_auto_update.sh [--force]
# Run by the launchd agent from scripts/install_auto_update.sh (every 30 min
# and at login); can also be run by hand.  Steps:
#   1. git fetch origin main in this clone (the clone itself is not touched:
#      the build happens in a separate worktree, ~/.cytosol-autoupdate/src)
#   2. stop if origin/main is the commit already installed (--force: rebuild)
#   3. build the app (build_mac.sh), run its --selftest, stop unless PASSED
#   4. write the versioned DMG to the Desktop (make_dmg.sh)
#   5. wait while the app is running, then swap it into /Applications;
#      the old app goes to ~/.Trash as "Cytosol Viewer <old version>.app"
# Every run also copies the Windows zip of the newest GitHub release (built
# by .github/workflows/build-windows.yml) to the Desktop.  Only the newest
# DMG and exe zip this script made stay there; older ones go to the Trash.
# Environment: PYTHON (python3.12 to build with; found automatically),
# MAKE_DMG=0 (no DMG), GET_EXE=0 (no Windows zip).
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

# put FILE on the Desktop as the current KIND (dmg / exe); the previous file
# of that kind that this script put there goes to the Trash
desktop_replace() {
  local kind=$1 file=$2 rec="$BASE/desktop_$1" prev
  prev=$(cat "$rec" 2>/dev/null || true)
  if [ -n "$prev" ] && [ "$prev" != "$file" ] && [ -e "$prev" ]; then
    mv "$prev" "$HOME/.Trash/" 2>/dev/null || mv "$prev" "$HOME/.Trash/$(date +%s)-$(basename "$prev")" || true
  fi
  echo "$file" > "$rec"
}

# Windows zip of the newest release -> Desktop (private repo: token from the
# git credential helper this clone already uses)
sync_exe() {
  local api=https://api.github.com/repos/windowrainYOON/cytosol-analysis
  local tok auth=() json name url out
  tok=$(printf 'protocol=https\nhost=github.com\n\n' \
        | GIT_TERMINAL_PROMPT=0 git -C "$REPO" credential fill 2>/dev/null \
        | sed -n 's/^password=//p') || true
  [ -n "$tok" ] && auth=(-H "Authorization: Bearer $tok")
  json=$(curl -fsSL ${auth[@]+"${auth[@]}"} "$api/releases/latest") || {
    log "exe: no release found"; return 0; }
  read -r name url < <(printf '%s' "$json" | "$PYTHON" -c '
import json, sys
for a in json.load(sys.stdin).get("assets", []):
    if a["name"].endswith("-Windows.zip"):
        print(a["name"], a["url"]); break') || true
  [ -n "${name:-}" ] || return 0
  out="$HOME/Desktop/$name"
  # once per release: a zip the user removed is not fetched again
  [ "$(cat "$BASE/desktop_exe" 2>/dev/null)" = "$out" ] && return 0
  curl -fsSL ${auth[@]+"${auth[@]}"} -H 'Accept: application/octet-stream' -o "$out.part" "$url" \
    && mv "$out.part" "$out" || { rm -f "$out.part"; log "exe: download failed"; return 0; }
  desktop_replace exe "$out"
  log "exe: $name on the Desktop"
}

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
[ "${GET_EXE:-1}" = 1 ] && sync_exe
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

if [ "${MAKE_DMG:-1}" = 1 ]; then
  if DMG=$(cd "$SRC" && ./make_dmg.sh 2>>"$BASE/build.log" | sed -n 's/^Built: //p') \
     && [ -n "$DMG" ]; then
    desktop_replace dmg "$DMG"
    log "DMG: $(basename "$DMG") on the Desktop"
  else
    log "DMG failed (the app is still installed)"
  fi
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
