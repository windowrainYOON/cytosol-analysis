"""Smoke test for a built app: ``"Cytosol Viewer" --selftest OUT_DIR``.

Runs the main code paths on a synthetic two-channel image (readers import,
LUT/TIFF export, cell ROI detection and ImageJ export, image-ID pairing of
exports, figure export, the main
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
                  colors=[(0.0, 0.3, 1.0), (0.0, 1.0, 0.0)],
                  metadata={'image_id': 'SELF-TEST-0001'})
    item = ImageItem(path=Path('selftest.tif'), image=image, label='selftest')
    item.reset_luts()
    item.add_crop(10, 10, 120, 120)
    return item


def _synthetic_tcf(path, nt=2):
    """Tiny Tomocube-like TCF: 3D RI (+2DMIP) and a 2-channel 3DFL on another grid."""
    import h5py

    rng = np.random.default_rng(1)
    with h5py.File(path, 'w') as f:
        ht = f.create_group('Data/3D')
        ht.attrs.update(SizeX=64, SizeY=60, SizeZ=12, ResolutionX=0.2, ResolutionY=0.2,
                        ResolutionZ=0.5, RIMin=1.33, RIMax=1.40)
        mip = f.create_group('Data/2DMIP')
        mip.attrs.update(SizeX=64, SizeY=60, ResolutionX=0.2, ResolutionY=0.2)
        fl = f.create_group('Data/3DFL')
        fl.attrs.update(SizeX=48, SizeY=45, SizeZ=5, ResolutionX=0.2667, ResolutionY=0.2667,
                        ResolutionZ=0.6, OffsetZ=3.0)
        for c, col in enumerate(((0, 255, 0), (255, 0, 255))):
            g = fl.create_group(f'CH{c}')
            g.attrs.update(ColorR=col[0], ColorG=col[1], ColorB=col[2],
                           Excitation=0.47 + c / 10, Emission=0.52 + c / 10)
        for t in range(nt):
            name = f'{t:06d}'
            vol = (13300 + rng.integers(0, 700, (12, 60, 64))).astype(np.uint16)
            ht.create_dataset(name, data=vol).attrs['Time'] = 60.0 * t
            mip.create_dataset(name, data=vol.max(0)).attrs['Time'] = 60.0 * t
            for c in range(2):
                d = fl[f'CH{c}'].create_dataset(
                    name, data=rng.integers(0, 4000, (5, 45, 48)).astype(np.uint16))
                d.attrs['Time'] = 60.0 * t


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

    export_item_files = []

    def tiff_export():
        from .lut import export_item
        export_item_files[:] = export_item(item, out / 'export', per_channel=True)
        return len(export_item_files)

    def time_series_export():
        from .io import Image
        from .lut import ImageItem, export_item
        from .render import TimeStampStyle
        frames = np.stack([item.image.data] * 3).astype(np.float32)
        image = Image(frames[0], list(item.channels), dict(item.image.voxel_size_um),
                      times=[0.0, 60.0, 120.0], loader=lambda t: frames[t])
        ts = ImageItem(path=Path('selftest_t.tif'), image=image, label='selftest_t')
        ts.reset_luts()
        files = export_item(ts, out / 'export_t', time=TimeStampStyle(bar=True))
        movies = export_item(ts, out / 'export_t_mp4', crops=False, raw_stack=False,
                             rgb_format='mp4', fps=5)
        if [Path(f).suffix for f in movies] != ['.mp4'] or Path(movies[0]).stat().st_size < 1000:
            raise AssertionError(f'MP4 export: {movies}')
        return f'{len(files)} files + {Path(movies[0]).name}, t restored to {ts.t}'

    def mp4_odd_size():
        import imageio_ffmpeg

        from .movie import write_mp4
        frames = [np.full((51, 77, 3), 40 * k, np.uint8) for k in range(4)]
        path = write_mp4(out / 'selftest_odd.mp4', frames, fps=2)
        reader = imageio_ffmpeg.read_frames(path)
        meta = next(reader)
        n = sum(1 for _ in reader)
        if n != 4 or tuple(meta['size']) != (78, 52):
            raise AssertionError(f'read back {n} frames of {meta["size"]}')
        return f'{n} frames {meta["size"]}, ffmpeg {imageio_ffmpeg.get_ffmpeg_version()}'

    def line_profile_step():
        from .lineprofile import line_profile, write_profile_csv
        from .profile_panel import save_profile_figure
        planes = item.planes()
        # across the nucleus at (70, 70): DAPI high in the middle, low at the ends
        prof = line_profile(planes, (30, 70, 110, 70), width=3, pixel_um=item.pixel_um,
                            channels=item.channels)
        mid = prof.values[0, len(prof.distance) // 2]
        if not (mid > 500 > prof.values[0, 0]) or not np.isclose(prof.length, 16.0):
            raise AssertionError(f'profile mid {mid}, ends {prof.values[0, 0]}, '
                                 f'length {prof.length}')
        write_profile_csv(out / 'selftest_profile.csv', prof)
        for ext in ('png', 'pdf'):
            save_profile_figure(out / f'selftest_profile.{ext}', prof,
                                [lut.color for lut in item.luts])
        return f'{len(prof.distance)} samples over {prof.length:.1f} {prof.unit}'

    def cell_rois():
        from .cellroi import segment_cells
        planes = item.planes()
        rois = segment_cells(planes[1], planes[0], item.pixel_um)
        item.cells = rois
        rois.save(out / 'selftest_RoiSet.zip', properties=item.id_properties())
        return f'{len(rois)} cells'

    def coloc2():
        from .coloc import Coloc2Settings, ValueType, run_coloc2
        from .coloc_panel import ColocRecord, region_mask, save_pdf_report, write_coloc_csv
        planes = item.planes()
        cells = item.cells
        recs = []
        for l in cells.ids():
            for key in ('cell', 'cyto'):
                m = region_mask(cells, l, key)
                res = run_coloc2(planes[0], planes[1], m,
                                 Coloc2Settings(costes_randomisations=5, display_images=True),
                                 ValueType.for_dtype('uint16'), ('DAPI', 'GFP'), f'{key}{l:03d}')
                recs.append(ColocRecord(item.label, item.image_id, item.source_name, 0, 'MIP',
                                        f'{key}{l:03d}', key, l, 'DAPI', 'GFP', int(m.sum()), res))
        r = recs[0].result
        names = [n for n, _, _ in r.values]
        for need in ("Pearson's R value (no threshold)", "Manders' tM1 (Above autothreshold of Ch2)",
                     "Kendall's Tau-b rank correlation value", 'Costes P-Value'):
            if need not in names:
                raise AssertionError(f'missing {need}')
        if len(r.histograms) != 3:
            raise AssertionError(f'{len(r.histograms)} histograms')
        n = write_coloc_csv(out / 'selftest_coloc2.csv', recs)
        save_pdf_report(out / 'selftest_coloc2.pdf', recs[0])
        item.coloc = recs
        return f'{n} ROIs, cell001 r = {r.value("Pearson\'s R value (no threshold)"):.3f}'

    def image_id_pairing():
        from .app import load_items
        from .imageid import plan_pairing, roi_id, tiff_id
        files = [Path(f) for f in export_item_files]
        ids = {tiff_id(f)[0] for f in files} | {roi_id(out / 'selftest_RoiSet.zip')}
        if ids != {item.image_id}:
            raise AssertionError(f'IDs in exports: {ids}')
        plan = plan_pairing(files + [out / 'selftest_RoiSet.zip'])
        best = plan['exports'][item.image_id][0]
        back = load_items(best)[0]
        if back.image_id != item.image_id or back.image.shape != item.image.shape:
            raise AssertionError(f'reloaded {best.name}: {back.image_id}')
        return f'{item.image_id} in {len(files)} TIFFs + RoiSet, reopened {best.name}'

    def same_name_export():
        from dataclasses import replace

        from .lut import export_all, export_item, item_folder
        twin = _synthetic_item()
        twin.image = replace(twin.image, metadata={'image_id': 'SELF-TEST-0002'})
        folders = {item_folder(it) for it in (item, twin)}
        if len(folders) != 2:
            raise AssertionError(f'per-image folders collide: {folders}')
        for it in (item, twin):
            export_item(it, out / 'same_name' / item_folder(it), crops=False, raw_stack=False)
        flat = export_all([item, twin], out / 'same_name_flat', crops=False, raw_stack=False)
        if len(set(flat)) != 2:
            raise AssertionError(f'flat export overwrote: {flat}')
        return ', '.join(sorted(folders))

    def figure():
        from .figure import FigureSpec, fill_row_by_channels, save_figure
        spec = FigureSpec()
        fill_row_by_channels(spec, 0, item)
        for ext in ('png', 'pdf', 'svg', 'tif'):
            save_figure(spec, out / f'selftest_figure.{ext}', dpi=100)

    def lazy_tcf():
        import time

        from .io import read_image
        path = out / 'selftest.TCF'
        _synthetic_tcf(path)
        image = read_image(path, aligned=True)
        if image.volume_loaded or image.shape != (3, 12, 60, 64):
            raise AssertionError(f'expected a lazy (3, 12, 60, 64) image: {image.shape}')
        t0 = time.perf_counter()
        planes = {z: image.plane(z) for z in ('mip', 0, 5, 11)}
        dt = time.perf_counter() - t0
        if image.volume_loaded:
            raise AssertionError('reading planes loaded the whole volume')
        vol = image.data
        for z, p in planes.items():
            ref = vol.max(axis=1) if z == 'mip' else vol[:, z]
            if not np.allclose(p, ref):
                raise AssertionError(f'plane {z} differs from the volume')
        image.load_time(1)
        if image.volume_loaded or image.t != 1:
            raise AssertionError('changing T kept the old volume')
        if not np.allclose(image.plane(5), image.data[:, 5]):
            raise AssertionError('plane at t=1 differs from the volume')
        return f'4 planes in {dt * 1000:.0f} ms, planes == volume at t 0 and 1'

    def projections():
        from .io import Image
        from .lut import ImageItem
        from .stack import StackView, export_projection, export_rotation, project_2d, project_3d
        rng = np.random.default_rng(2)
        vol = rng.random((2, 8, 40, 50)).astype(np.float32) * 100
        image = Image(vol, ['A', 'B'], {'Z': 0.6, 'Y': 0.2, 'X': 0.2},
                      colors=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
        it = ImageItem(path=Path('selftest_stack.tif'), image=image, label='stack')
        it.reset_luts()
        p0 = project_3d(vol, 0, 'Y', 3.0)
        off = [o for o in range(p0.shape[2] - 49) if np.array_equal(p0[:, :, o:o + 50],
                                                                     project_2d(vol))]
        if not off:
            raise AssertionError('3D projection at 0 degrees != 2D max projection')
        view = StackView(it)
        view.settings.method_2d = 'sum'
        view.compute()
        view.sync()
        if not np.isclose(view.luts[0].vmax, it.luts[0].vmax * 8):
            raise AssertionError('sum projection LUT not scaled by the slice count')
        view.settings.mode, view.settings.angle = '3d', 30
        res = view.compute()
        built = view.raw3d_key
        view.settings.angle = 60
        view.preview_rgb()
        if view.raw3d_key != built:
            raise AssertionError('turning the 3D view rebuilt its structure')
        view.luts[0].vmax *= 0.5
        if not view.lut_stale():
            raise AssertionError('LUT change not flagged for 3D refresh')
        view.refresh_3d()
        if view.lut_stale():
            raise AssertionError('3D refresh did not apply the LUT')
        files = export_projection(view, out / 'stack' / 'selftest_3d')
        files += export_rotation(view, out / 'stack' / 'selftest_rot', range(0, 90, 30))
        files += export_rotation(view, out / 'stack' / 'selftest_rot', range(0, 90, 30),
                                 movie_fps=5)
        if not files[-1].endswith('.mp4'):
            raise AssertionError(f'rotation MP4: {files[-1]}')
        return f'3D {res.shape}, {len(files)} files'

    def window():
        from PySide6.QtWidgets import QApplication

        from .app import MainWindow
        from .figure_window import FigureWindow  # noqa: F401
        app = QApplication.instance() or QApplication([sys.argv[0]])
        win = MainWindow()
        win.show()
        app.processEvents()
        win.add_files([out / 'selftest.TCF'])
        win.z_slider.setValue(4)
        win._z_changed()
        win.right_tabs.setCurrentIndex(win.stack_tab)
        app.processEvents()
        win.stack_panel.mode_3d.setChecked(True)
        win.stack_panel.angle_spin.setValue(45)
        win.update_preview()
        app.processEvents()
        if win.current.z != 3 or win.stack_views[id(win.current)].result is None:
            raise AssertionError('Z slider / stack tab did not update')
        win.right_tabs.setCurrentIndex(0)
        app.processEvents()
        if win.current.image.volume_loaded:
            raise AssertionError('volume kept after leaving the stack tab')
        win.line_btn.setChecked(True)
        app.processEvents()
        if win.right_tabs.currentIndex() != win.profile_tab or not win.canvas.line_mode:
            raise AssertionError('line profile mode did not open its tab')
        win.canvas.lineDrawn.emit(5.0, 5.0, 50.0, 40.0)
        win.profile_panel.width.setValue(3)
        win.profile_panel.refresh()
        prof = win.profile_panel.profile
        if prof is None or prof.values.shape[0] != len(win.current.channels):
            raise AssertionError('no profile after drawing a line')
        if not win.canvas._line_items:
            raise AssertionError('profile line not drawn on the canvas')
        win.coloc_panel.whole.setChecked(True)
        win.coloc_panel.nrand.setValue(3)
        win.coloc_panel._run([win.current])
        win.coloc_panel.bind(win.current)
        if not win.current.coloc or win.coloc_panel.table.rowCount() != len(win.current.coloc):
            raise AssertionError('Coloc 2 tab produced no results')
        win.coloc_panel._draw()
        # channel 표시 checkboxes gathered in one row; all off / all on
        row = win.visibility
        if [p.visible.text() for p in row.panels] != list(win.current.channels):
            raise AssertionError('visibility row not labelled with the channel names')
        row.set_all(False)
        if any(lut.visible for lut in win.current.luts) or any(
                p.visible.isChecked() for p in row.panels):
            raise AssertionError('"all off" left a channel visible')
        row.set_all(True)
        if not all(lut.visible for lut in win.current.luts):
            raise AssertionError('"all on" left a channel hidden')
        # multi-select removal
        win.add_files([out / 'selftest.TCF'])
        win.add_files([out / 'selftest.TCF'])
        n = len(win.items)
        win.file_list.clearSelection()
        win.file_list.setCurrentRow(n - 1)
        win.file_list.item(n - 2).setSelected(True)
        win.remove_selected()
        app.processEvents()
        if len(win.items) != n - 2 or win.file_list.count() != n - 2 \
                or win.current is not win.items[-1]:
            raise AssertionError('multi-select removal')
        win.file_list.selectAll()
        win.remove_selected()
        if win.items or win.current is not None or row.panels:
            raise AssertionError('removing every image left state behind')
        win.close()

    step('readers import', readers)
    step('HDF5 non-ASCII path', hdf5_unicode_path)
    step('TIFF export', tiff_export)
    step('time-series export', time_series_export)
    step('MP4 (odd frame size)', mp4_odd_size)
    step('line profile', line_profile_step)
    step('cell ROIs + RoiSet.zip', cell_rois)
    step('Coloc 2 per cell ROI', coloc2)
    step('image ID in exports + pairing', image_id_pairing)
    step('same-name images, separate folders', same_name_export)
    step('figure export', figure)
    step('lazy TCF planes', lazy_tcf)
    step('Z-stack projections', projections)
    step('main window', window)

    text = '\n'.join(log) + f'\n\n{"PASSED" if ok else "FAILED"}\n'
    (out / 'selftest.log').write_text(text, encoding='utf-8')
    if sys.stdout is not None:
        print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else 'selftest-out'))
