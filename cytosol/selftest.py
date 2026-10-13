"""Smoke test for a built app: ``"Cytosol Viewer" --selftest OUT_DIR``.

Runs the main code paths on a synthetic two-channel image (readers import,
LUT/TIFF export, cell ROI detection and ImageJ export, figure export, the main
window) so a packaged build can be checked without a real data file.
Writes the outputs and ``selftest.log`` into OUT_DIR; exit code 0 = passed.
"""

import os
import sys
import traceback
from pathlib import Path

import numpy as np


def _synthetic_item():
    from .io import Image
    from .lut import ImageItem

    yy, xx = np.mgrid[0:256, 0:256]
    nuc = np.zeros((256, 256), np.float32)
    bg = np.full((256, 256), 5, np.float32)
    for cy, cx in ((70, 70), (70, 180), (180, 120)):
        r2 = (yy - cy) ** 2 + (xx - cx) ** 2
        nuc[r2 < 15 ** 2] = 1000
        bg[r2 < 45 ** 2] = 60
    rng = np.random.default_rng(0)
    data = np.stack([nuc, bg])[:, None] + rng.normal(0, 3, (2, 1, 256, 256))
    image = Image(data=np.clip(data, 0, None).astype(np.uint16), channels=['DAPI', 'GFP'],
                  voxel_size_um={'Z': None, 'Y': 0.2, 'X': 0.2},
                  colors=[(0.0, 0.3, 1.0), (0.0, 1.0, 0.0)])
    item = ImageItem(path=Path('selftest.tif'), image=image, label='selftest')
    item.reset_luts()
    item.add_crop(10, 10, 120, 120)
    return item


def run(out_dir) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    log = []
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            res = fn()
            log.append(f'ok    {name}' + (f': {res}' if res is not None else ''))
        except Exception:
            ok = False
            log.append(f'FAIL  {name}\n{traceback.format_exc()}')

    def readers():
        import czifile, h5py, imagecodecs, oirfile, roifile, tifffile, xarray  # noqa: F401
        return f'h5py {h5py.__version__}, hdf5 {h5py.version.hdf5_version}'

    def hdf5_unicode_path():
        import h5py
        p = out / '한글 경로 테스트.h5'
        with h5py.File(p, 'w') as f:
            f['x'] = np.arange(3)
        with h5py.File(p, 'r') as f:
            return int(f['x'][()].sum())

    item = _synthetic_item()

    def tiff_export():
        from .lut import export_item
        return len(export_item(item, out / 'export', per_channel=True))

    def cell_rois():
        from .cellroi import segment_cells
        planes = item.planes()
        rois = segment_cells(planes[1], planes[0], item.pixel_um)
        item.cells = rois
        rois.save(out / 'selftest_RoiSet.zip')
        return f'{len(rois)} cells'

    def figure():
        from .figure import FigureSpec, fill_row_by_channels, save_figure
        spec = FigureSpec()
        fill_row_by_channels(spec, 0, item)
        for ext in ('png', 'pdf', 'svg', 'tif'):
            save_figure(spec, out / f'selftest_figure.{ext}', dpi=100)

    def window():
        from PySide6.QtWidgets import QApplication

        from .app import MainWindow
        from .figure_window import FigureWindow  # noqa: F401
        app = QApplication.instance() or QApplication([sys.argv[0]])
        win = MainWindow()
        win.show()
        app.processEvents()
        win.close()

    step('readers import', readers)
    step('HDF5 non-ASCII path', hdf5_unicode_path)
    step('TIFF export', tiff_export)
    step('cell ROIs + RoiSet.zip', cell_rois)
    step('figure export', figure)
    step('main window', window)

    text = '\n'.join(log) + f'\n\n{"PASSED" if ok else "FAILED"}\n'
    (out / 'selftest.log').write_text(text, encoding='utf-8')
    if sys.stdout is not None:
        print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else 'selftest-out'))
