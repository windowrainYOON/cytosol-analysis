"""Entry point for the Cytosol Viewer desktop app (used by PyInstaller).

``--selftest OUT_DIR`` runs cytosol.selftest instead of opening the window.
"""

import sys

if __name__ == '__main__':
    if len(sys.argv) > 2 and sys.argv[1] == '--selftest':
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from cytosol.selftest import run
        sys.exit(run(sys.argv[2]))
    from cytosol.app import main
    sys.exit(main())
