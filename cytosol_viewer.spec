# PyInstaller spec for Cytosol Viewer.  Build with ./build_mac.sh
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules('imagecodecs')
    + collect_submodules('czifile')
    + collect_submodules('oirfile')
    + collect_submodules('skimage')
    + ['h5py', 'tifffile', 'xarray', 'roifile']
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
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Cytosol Viewer')
app = BUNDLE(
    coll,
    name='Cytosol Viewer.app',
    icon='cytosol/assets/icon.icns',
    bundle_identifier='com.windowrainyoon.cytosolviewer',
    info_plist={
        'NSHighResolutionCapable': True,
        'CFBundleShortVersionString': '0.2.0',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'Microscopy image',
                'CFBundleTypeRole': 'Viewer',
                'LSItemContentTypes': ['public.data'],
                'CFBundleTypeExtensions': ['tcf', 'TCF', 'czi', 'oir'],
            }
        ],
    },
)
