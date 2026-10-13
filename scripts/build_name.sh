#!/usr/bin/env bash
# Print the versioned build name, e.g. CytosolViewer-0.3.0-a1b2c3d
# (version from cytosol/version.py, short commit, "-dirty" if uncommitted changes).
set -euo pipefail
cd "$(dirname "$0")/.."
VER=$(sed -n "s/^__version__ = '\(.*\)'/\1/p" cytosol/version.py)
SHA=$(git rev-parse --short=7 HEAD 2>/dev/null || echo nogit)
DIRTY=""
git diff --quiet HEAD -- 2>/dev/null || DIRTY="-dirty"
echo "CytosolViewer-${VER}-${SHA}${DIRTY}"
