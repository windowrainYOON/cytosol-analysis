# PyInstaller spec for Cytosol Viewer on Windows.  Build with build_windows.ps1
# (the macOS build uses cytosol_viewer.spec).  Output: dist/Cytosol Viewer/Cytosol Viewer.exe
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules('imagecodecs')
    + collect_submodules('czifile')
    + collect_submodules('oirfile')
    + collect_submodules('skimage')
    + ['h5py', 'tifffile', 'xarray', 'roifile',
       # figure export picks the backend by file type at save time
       'matplotlib.backends.backend_pdf', 'matplotlib.backends.backend_svg',
       'matplotlib.backends.backend_ps']
)
datas = collect_data_files('skimage') + [('cytosol/assets', 'cytosol/assets')]

a = Analysis(
    ['cytosol_viewer.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'IPython', 'pytest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Cytosol Viewer',
    icon='cytosol/assets/icon.ico',
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Cytosol Viewer')
