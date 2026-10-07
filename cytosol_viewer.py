"""Entry point for the Cytosol Viewer desktop app (used by PyInstaller)."""

import sys

from cytosol.app import main

if __name__ == '__main__':
    sys.exit(main())
