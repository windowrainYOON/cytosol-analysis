#!/usr/bin/env bash
# Install (or remove) the launchd agent that keeps
# /Applications/Cytosol Viewer.app up to date with origin/main.
#   scripts/install_auto_update.sh            install, run once now
#   scripts/install_auto_update.sh --uninstall
# The agent runs a copy of scripts/mac_auto_update.sh (~/.cytosol-autoupdate,
# kept at main's version by the script itself) for this clone at login and
# every 30 minutes.  Log: ~/Library/Logs/CytosolViewer-autoupdate.log
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
LABEL=com.windowrainyoon.cytosolviewer.autoupdate
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/CytosolViewer-autoupdate.log"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs" "$HOME/.cytosol-autoupdate"
cp "$REPO/scripts/mac_auto_update.sh" "$HOME/.cytosol-autoupdate/mac_auto_update.sh"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$HOME/.cytosol-autoupdate/mac_auto_update.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>CYTOSOL_REPO</key><string>$REPO</string>
    <key>MAKE_DMG</key><string>${MAKE_DMG:-1}</string>
    <key>GET_EXE</key><string>${GET_EXE:-1}</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>1800</integer>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL (runs now, then every 30 min); log: $LOG"
