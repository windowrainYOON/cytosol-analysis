#!/bin/zsh
# Background 일괄 분석 of a folder (on the CW Data disk or anywhere).
#   scripts/run_batch_bg.sh FOLDER [batch_folder.py options…]
# e.g.
#   scripts/run_batch_bg.sh "/Volumes/CW Data/Data (2026.01~)/Microscopy/Tomocube/261118" --match T001P --steps track
# Checks / mounts CW Data, then runs scripts/batch_folder.py under caffeinate
# with nohup; the log goes to ~/Library/Logs/cytosol-batch/<time>.log (path printed).
# Progress: grep -E '^\[|DONE' <log>
set -u
REPO="${0:A:h:h}"
FOLDER="$1"; shift
VOL="/Volumes/CW Data"
if [[ "$FOLDER" == "$VOL"* ]]; then
  if ! mount | grep -q "on $VOL "; then
    DEV=$(diskutil list external | awk '/CW Data/{print $NF; exit}')
    [[ -n "$DEV" ]] && diskutil mount "$DEV" >/dev/null 2>&1
  fi
  if ! ls "$VOL" >/dev/null 2>&1; then
    echo "CW Data is not readable (unplug and replug the disk, then: diskutil mount <disk>s1)"; exit 2
  fi
fi
[[ -d "$FOLDER" ]] || { echo "no folder: $FOLDER"; exit 2; }
LOGDIR="$HOME/Library/Logs/cytosol-batch"; mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(date +%y%m%d-%H%M%S).log"
nohup caffeinate -i "$REPO/.venv/bin/python" -u "$REPO/scripts/batch_folder.py" "$FOLDER" "$@" > "$LOG" 2>&1 &
echo "pid $! log $LOG"
