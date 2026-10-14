# PyInstaller spec for Cytosol Viewer.  Build with ./build_mac.sh
import re
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

VERSION = re.search(r"__version__ = '(.+)'", open('cytosol/version.py').read()).group(1)

hiddenimports = (
    collect_submodules('imagecodecs')
    + collect_submodules('czifile')
    + collect_submodules('oirfile')
    + collect_submodules('skimage')
    + ['h5py', 'tifffile', 'xarray', 'roifile',
       # figure export picks the backend by file type at save time
       'matplotlib.backends.backend_pdf', 'matplotlib.backends.backend_svg',
       'matplotlib.backends.backend_ps',
       # line profile plot embedded in the window
       'matplotlib.backends.backend_qtagg', 'imageio_ffmpeg']
)
# imageio-ffmpeg ships the ffmpeg binary used for MP4 export
datas = collect_data_files('skimage') + collect_data_files('imageio_ffmpeg', include_py_files=False) + [('cytosol/assets', 'cytosol/assets')]

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
        'CFBundleShortVersionString': VERSION,
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
