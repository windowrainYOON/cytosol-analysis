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


def ndi_fill(m):
    from scipy import ndimage

    return ndimage.binary_fill_holes(m)


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
        import roifile
        from PIL import Image
        from . import imageid
        from .imageid import ID_KEY
        from .lineprofile import line_profile, read_line_roi, write_profile_csv
        from .profile_panel import save_profile_companions, save_profile_figure
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
        roi_path, png_path = save_profile_companions(out / 'selftest_profile.png', item, prof)
        roi = roifile.ImagejRoi.fromfile(roi_path)
        if (roi.roitype != roifile.ROI_TYPE.LINE or roi.stroke_width != 3
                or not np.allclose([roi.x1, roi.y1, roi.x2, roi.y2], prof.line)
                or roi.properties.get(ID_KEY) != item.image_id):
            raise AssertionError(f'line ROI read back as {roi}')
        if read_line_roi(roi_path) != (tuple(prof.line), 3):
            raise AssertionError(f'line ROI reads back as {read_line_roi(roi_path)}')
        if imageid.roi_id(roi_path) != item.image_id:
            raise AssertionError('line ROI lost the image ID')
        overlay = np.asarray(Image.open(png_path))
        if overlay.shape[2] != 3 or overlay.shape[1] % planes.shape[-1]:
            raise AssertionError(f'overlay image {overlay.shape}')
        return f'{len(prof.distance)} samples over {prof.length:.1f} {prof.unit}'

    def cell_rois():
        from .cellroi import segment_cells
        planes = item.planes()
        rois = segment_cells(planes[1], planes[0], item.pixel_um)
        item.cells = rois
        rois.save(out / 'selftest_RoiSet.zip', properties=item.id_properties())
        return f'{len(rois)} cells'

    def cell_size_range():
        from .cellroi import RoiParams, segment_cells, size_range, threshold_cells
        yy, xx = np.mgrid[0:256, 0:256]
        bg = np.full((256, 256), 5, np.float32)
        nuc = np.zeros_like(bg)
        for cy, cx in ((128, 95), (128, 160)):  # two touching cells
            bg[(yy - cy) ** 2 + (xx - cx) ** 2 < 45 ** 2] = 60
            nuc[(yy - cy) ** 2 + (xx - cx) ** 2 < 14 ** 2] = 1000
        bg += np.random.default_rng(0).normal(0, 3, bg.shape).astype(np.float32)
        one = segment_cells(bg, None, 0.2)
        two = segment_cells(bg, None, 0.2, RoiParams(fit_size=True, min_cell_um2=120,
                                                     max_cell_um2=300))
        if len(one) != 1 or len(two) != 2:
            raise AssertionError(f'size fit: {len(one)} -> {len(two)} cells (want 1 -> 2)')
        a = [m['cell_area_um2'] for m in two.measurements()]
        if not all(120 <= x <= 300 for x in a):
            raise AssertionError(f'split cells outside the range: {a}')
        # manual mode: at or above the threshold is the ROI, nothing else
        man = threshold_cells(bg, nuc, 0.2, 30, 500, RoiParams(min_cell_um2=5))
        if len(man) != 1 or (man.labels > 0).sum() != ndi_fill(bg >= 30).sum():
            raise AssertionError('manual threshold ROI is not the area >= threshold')
        if not len(threshold_cells(bg, nuc, 0.2, 30, None, RoiParams(max_cell_um2=400))) == 0:
            raise AssertionError('manual mode ignored the maximum cell size')
        if size_range([100, 120, 130, 140, 150, 5000]) != (100.0, 150.0):
            raise AssertionError(f'size_range outlier: {size_range([100, 120, 130, 140, 150, 5000])}')
        return f'touching cells 1 -> 2 ({a[0]:.0f}, {a[1]:.0f} µm²), manual threshold ROI'

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

    def intensity():
        from .intensity import (ParticleSettings, detect_particles, is_particle_file,
                                contour_particles, is_contour_file, load_particles, make_regions, measure_cells,
                                measure_particles, save_particle_sets, save_particles, write_rows)
        planes = item.planes()
        cells = item.cells
        # two bright spots in every cytosol of the GFP channel
        img = planes.copy()
        yy, xx = np.mgrid[:img.shape[1], :img.shape[2]]
        for l in cells.ids():
            cx, cy = cells.centroid(l)
            for dx in (-30, 30):
                img[1][(yy - cy) ** 2 + (xx - cx - dx) ** 2 < 16] = 900
        s = ParticleSettings('GFP', 1, 'cyto', 'otsu', 0, 5)
        p = detect_particles(cells, img[1], s, 16)
        counts = p.counts(cells)
        if any(counts.get(l) != 2 for l in cells.ids()):
            raise AssertionError(f'particles per cell: {counts}')
        regions = make_regions(['cell', 'nuc', 'cyto', 'particle'], ['cyto - particle'])
        rows = measure_cells(img, cells, regions, item.channels, item.pixel_um, p,
                             stats=('Mean', 'RawIntDen'))
        by = {(r['roi'], r['region']): r for r in rows}
        for l in cells.ids():
            k = f'cell{l:03d}'
            if by[k, 'particle']['GFP_Mean'] != 900:
                raise AssertionError(f'{k} particle mean {by[k, "particle"]["GFP_Mean"]}')
            if by[k, 'particle']['area_px'] + by[k, 'cyto - particle']['area_px'] \
                    != by[k, 'cytosol']['area_px']:
                raise AssertionError(f'{k}: particle + rest != cytosol')
            cell = cells.labels == l
            if not np.isclose(by[k, 'cell']['DAPI_Mean'], img[0][cell].mean(), rtol=1e-6):
                raise AssertionError(f'{k} cell mean')
        write_rows(out / 'selftest_intensity.csv', rows)
        # one row per particle: round discs 60 px apart, partition = particle / rest
        prow = measure_particles(img, cells, p, item.channels, item.pixel_um, stats=('Mean',))
        if len(prow) != 2 * len(cells.ids()):
            raise AssertionError(f'per-particle rows {len(prow)}')
        unit = 'um' if item.pixel_um else 'px'
        cal = item.pixel_um or 1.0
        for r in prow:
            if not (r['circularity'] > 0.85 and r['solidity'] > 0.85 and r['aspect_ratio'] < 1.15):
                raise AssertionError(f'disc shape {r}')
            if abs(r[f'nnd_{unit}'] - 60 * cal) > 0.5 * cal:
                raise AssertionError(f'nearest neighbour {r[f"nnd_{unit}"]}')
            rest = by[r['roi'], 'cyto - particle']['GFP_Mean']
            if not np.isclose(r['GFP_partition'], 900 / rest, rtol=1e-5):
                raise AssertionError(f'partition {r["GFP_partition"]} vs {900 / rest}')
        write_rows(out / 'selftest_particle_shape.csv', prow)
        zp = save_particles(out / 'selftest_particles.zip', cells, p, item.id_properties())
        back, s2 = load_particles(zp, cells.shape)
        if (back.mask ^ p.mask).any() or s2 != s or not is_particle_file(zp):
            raise AssertionError('particle ROI round trip')
        if len(type(cells).load(zp, cells.shape)) != 0:
            raise AssertionError('particle ROIs read as cells')
        # automatic spot detection: a touching pair and a dim spot per cytosol
        img = planes[1].astype(np.float32).copy()
        spots = []
        for l in cells.ids():
            cx, cy = cells.centroid(l)
            spots += [(cx - 30, cy, 400), (cx - 30, cy + 4, 400), (cx + 30, cy, 60)]
        for x, y, a in spots:
            img += a * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.5 ** 2))
        sa = ParticleSettings('GFP', 1, 'cyto', 'auto', min_px=3, k=4.0)
        pa = detect_particles(cells, img, sa, 16, item.pixel_um)
        ca = pa.counts(cells)
        if any(ca.get(l) != 3 for l in cells.ids()):
            raise AssertionError(f'auto particles per cell: {ca}')
        comp = pa.components(cells)
        hit = {int(comp[int(round(y)), int(round(x))]) for x, y, _ in spots}
        if 0 in hit or len(hit) != len(spots):
            raise AssertionError('auto particles miss or merge spots')
        zp = save_particles(out / 'selftest_particles_auto.zip', cells, pa)
        back, s3 = load_particles(zp, cells.shape)
        if s3 != sa or back.counts(cells) != ca or (back.mask ^ pa.mask).any():
            raise AssertionError('auto particle ROI round trip')
        # shape from sub-pixel iso-intensity outlines (half max), intensity from pixels
        crow = measure_particles(img[None], cells, pa, ['GFP'], item.pixel_um,
                                 contour_plane=img, contour_level=0.5)
        prow = {r['particle']: r for r in measure_particles(img[None], cells, pa, ['GFP'],
                                                            item.pixel_um)}
        for r in crow:
            if r['shape_outline'] != 'iso-contour 0.5' or r['GFP_Mean'] != prow[r['particle']]['GFP_Mean']:
                raise AssertionError(f'contour row {r}')
        lone = [r for r in crow if r['GFP_Mean'] < 150]  # the dim round spots, alone
        if len(lone) != len(cells.ids()) or any(r['circularity'] < 0.92 or r['solidity'] < 0.98
                                                for r in lone):
            raise AssertionError(f'iso-contour shape of round spots {lone}')
        # intensities inside the iso-contours: fewer pixels, brighter mean, same particles
        irow = measure_particles(img[None], cells, pa, ['GFP'], item.pixel_um,
                                 contour_plane=img, contour_level=0.5, intensity_level=0.5)
        for r in irow:
            q = prow[r['particle']]
            if r['intensity_roi'] != 'iso-contour 0.5' or not 0 < r['area_px'] <= q['area_px'] \
                    or r['GFP_Mean'] < q['GFP_Mean'] - 1e-6:
                raise AssertionError(f'contour intensity {r} vs {q}')
        cp = contour_particles(img, cells, pa, 0.5)
        if cp.counts(cells) != ca or (cp.mask & ~pa.mask).sum() > pa.mask.sum() // 2:
            raise AssertionError('contour particles')
        files = save_particle_sets(out / 'selftest_particles_iso.zip', cells, pa, None, img, 0.5)
        if len(files) != 2 or not is_contour_file(files[1]) or is_particle_file(files[1]) \
                or not is_particle_file(files[0]):
            raise AssertionError(f'contour ROI files {files}')
        return f'{len(rows)} rows, {sum(counts.values())} particles, auto {sum(ca.values())}'

    def image_id_pairing():
        from .app import load_items
        from .imageid import plan_pairing, roi_id, tiff_id
        from .crops import is_crop_file, load_crop_rois
        crop_zips = [Path(f) for f in export_item_files if f.endswith('_crops.zip')]
        if len(crop_zips) != 1 or not is_crop_file(crop_zips[0]) \
                or load_crop_rois(crop_zips[0]) != item.crops:
            raise AssertionError(f'crop ROI file: {crop_zips}')
        files = [Path(f) for f in export_item_files if f.endswith('.tif')]
        ids = {tiff_id(f)[0] for f in files} | {roi_id(out / 'selftest_RoiSet.zip')} \
            | {roi_id(crop_zips[0])}
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

    def read_ahead():
        import time

        from scipy import ndimage as ndi

        from .io import _FlMapper
        from .lut import ImageItem
        from .io import Image
        from .prefetch import TimeCache, plane_at, preview_at, reads_ahead
        # the fast FL resampling gives ndimage's pixels
        hg = {'nx': 64, 'ny': 60, 'nz': 12, 'rx': 0.2, 'ry': 0.2, 'rz': 0.5}
        fg = {'nx': 48, 'ny': 45, 'nz': 5, 'rx': 0.2667, 'ry': 0.2667, 'rz': 0.6}
        m = _FlMapper(hg, fg, 0.5, shift_px=(0.3, -0.7))
        src = np.random.default_rng(3).random((45, 48)).astype(np.float32)
        ref = ndi.affine_transform(src, [m.sy, m.sx], offset=[m.oy, m.ox],
                                   output_shape=m.shape, order=1)
        if not np.allclose(m.xy(src), ref, atol=1e-5):
            raise AssertionError('fast FL resampling differs from ndimage')
        path = out / 'selftest_t4.TCF'
        _synthetic_tcf(path, nt=4)
        item = ImageItem.load(path, aligned=True)
        item.z = 5
        tc = TimeCache()
        item.time_cache = tc
        if not reads_ahead(item):
            raise AssertionError('a Z+T image is not read ahead')
        # Z-stack time series: every timepoint of the current Z is read ahead
        t0 = time.perf_counter()
        tc.follow(item)
        while tc.cached(item, exact=True) < item.nt:
            if time.perf_counter() - t0 > 30:
                raise AssertionError(f'read ahead {tc.cached(item, exact=True)}/{item.nt}')
            time.sleep(0.01)
        dt = time.perf_counter() - t0
        for t in range(item.nt):
            if not np.array_equal(tc.get(item, t), plane_at(item.image, t, 5)):
                raise AssertionError(f'read-ahead plane at t={t} differs')
        item.set_t(3)
        if not np.allclose(item.planes(), item.image.data[:, 5], atol=1e-3):
            raise AssertionError('read-ahead plane differs from the volume')
        # MIP while dragging: a quick approximate plane, the exact one on release
        prev, ok = preview_at(item.image, 2, 'mip')
        exact = item.image.plane_loader(2, 'mip')
        if ok or prev.shape != exact.shape or not np.array_equal(prev[0], exact[0]):
            raise AssertionError('MIP preview: flagged exact, wrong shape or RI channel')
        item.z = 'mip'
        item.set_t(2)
        item.show_planes(prev, ok)
        item.drop_preview()
        if not np.array_equal(item.planes(), exact):
            raise AssertionError('exact MIP not restored after the preview')
        tc.follow(None)
        # single-plane time series: no read-ahead, only the last few planes
        rng = np.random.default_rng(4)
        frames = rng.random((6, 2, 1, 30, 40)).astype(np.float32)
        flat = ImageItem(path=Path('selftest_t2d.tif'), label='t2d', image=Image(
            frames[0], ['A', 'B'], {'Z': None, 'Y': 0.2, 'X': 0.2},
            times=[10.0 * i for i in range(6)], loader=lambda t: frames[t]))
        flat.reset_luts()
        if reads_ahead(flat):
            raise AssertionError('a single-plane time series is read ahead')
        tc.follow(flat)
        for t in range(6):
            tc.follow(flat, t)
            while tc.get(flat, t) is None:
                if time.perf_counter() - t0 > 30:
                    raise AssertionError(f'background load of t={t} did not finish')
                time.sleep(0.01)
            if not np.array_equal(tc.get(flat, t), frames[t][:, 0]):
                raise AssertionError(f'background plane at t={t} differs')
        if tc.cached(flat) > tc.keep:
            raise AssertionError(f'kept {tc.cached(flat)} planes, limit {tc.keep}')
        tc.follow(None)
        return f'{item.nt} Z+T timepoints read ahead in {dt * 1000:.0f} ms; 2D+T keeps {tc.keep}'

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
        import time

        from PySide6.QtWidgets import QApplication

        from .app import MainWindow
        from .figure_window import FigureWindow  # noqa: F401
        app = QApplication.instance() or QApplication([sys.argv[0]])
        win = MainWindow()
        win.show()
        app.processEvents()
        tabs = [win.right_tabs.tabText(i) for i in range(win.right_tabs.count())]
        if tabs != ['LUT', '이미지 정보']:
            raise AssertionError(f'tabs at start: {tabs}')
        win.add_files([out / 'selftest.TCF'])
        win.add_files([out / 'selftest.TCF'], explicit=True)
        if len(win.items) != 1:
            raise AssertionError('불러오기 opened an image that is already in the list')
        if win.info_panel.summary is None or win.info_panel.gen.rowCount() == 0:
            raise AssertionError('image info tab empty')
        # dragging T draws read-ahead timepoints; releasing settles on the last one
        win.t_slider.setSliderDown(True)
        win.t_slider.setValue(1)
        t0 = time.perf_counter()
        while win.current.t != 1 and time.perf_counter() - t0 < 30:
            app.processEvents()
            time.sleep(0.01)
        win.t_slider.setSliderDown(False)
        win.t_slider.sliderReleased.emit()
        app.processEvents()
        if win.current.t != 1:
            raise AssertionError('dragging the T slider did not show t=2')
        if win.current._planes_preview or not np.array_equal(
                win.current.planes(), win.current.image.plane_loader(1, win.current.z)):
            raise AssertionError('releasing the T slider kept the preview plane')
        # right-drag on the image: left/right = T, up/down = Z, drawn while moving
        it = win.current
        if not win._can_scrub():
            raise AssertionError('right-drag through T/Z not offered for a Z+T image')
        win.canvas.scrubStarted.emit()
        win.canvas.scrubDragged.emit(-win.canvas.viewport().width(), -40.0)
        t0 = time.perf_counter()
        while win._t_want is not None and time.perf_counter() - t0 < 30:
            app.processEvents()
            time.sleep(0.01)
        win.canvas.scrubEnded.emit()
        app.processEvents()
        if it.t != 0 or it.z in ('mip', 'mid') or it.z <= it.nz // 2:
            raise AssertionError(f'right-drag ended at t={it.t}, z={it.z}')
        if win.t_slider.value() != 0 or win.z_slider.value() != it.z + 1:
            raise AssertionError('right-drag did not move the T / Z sliders')
        if it._planes_preview or not np.allclose(
                it.planes(), it.image.plane_loader(0, it.z), atol=1e-3):
            raise AssertionError('right-drag left a wrong plane')
        win.z_slider.setValue(4)
        win._z_changed()
        win.show_tab('stack_tab')
        app.processEvents()
        win.stack_panel.mode_3d.setChecked(True)
        win.stack_panel.angle_spin.setValue(45)
        win.update_preview()
        app.processEvents()
        if win.current.z != 3 or win.stack_views[id(win.current)].result is None:
            raise AssertionError('Z slider / stack tab did not update')
        # 3D view: right-drag turns (up-down switches to the X axis from 0°)
        if not win.canvas.view3d:
            raise AssertionError('3D view not draggable')
        win.canvas.rotateStarted.emit()
        win.canvas.rotateDragged.emit('X', 40.0)
        sp = win.stack_panel
        if sp.axis.currentData() != 'X' or sp.angle_spin.value() != 20:
            raise AssertionError(f'3D drag: {sp.axis.currentData()} {sp.angle_spin.value()}')
        win.canvas.rotateDragged.emit('X', 100.0)
        if sp.angle_spin.value() != 50:
            raise AssertionError('3D drag did not follow the mouse')
        win.right_tabs.setCurrentIndex(0)
        app.processEvents()
        if win.current.image.volume_loaded:
            raise AssertionError('volume kept after leaving the stack tab')
        if win.canvas.view3d:
            raise AssertionError('3D drag mode left on outside the stack tab')
        # crop regions: drag one to move it (kept inside the image, same size)
        h, w = win.current.image.shape[-2:]
        win._crop_drawn(2, 2, 12, 10)
        win.canvas.cropMoved.emit(0, 5, 3)
        if win.current.crops[0] != (7, 5, 17, 13):
            raise AssertionError(f'crop move: {win.current.crops[0]}')
        win.canvas.cropMoved.emit(0, 10 * w, -10 * h)
        if win.current.crops[0] != (w - 10, 0, w, 8):
            raise AssertionError(f'crop move not clamped: {win.current.crops[0]}')
        win.clear_crops()
        # rectangle zoom
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtTest import QTest
        win.canvas.fit()
        before = win.canvas.transform().m11()
        win.zoom_btn.setChecked(True)
        vp = win.canvas.viewport()
        c = vp.rect().center()
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, c)
        QTest.mouseMove(vp, c + QPoint(20, 20))
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           c + QPoint(20, 20))
        if win.zoom_btn.isChecked() or win.canvas.transform().m11() <= before * 2:
            raise AssertionError('rectangle zoom')
        win.canvas.fit()
        win.line_btn.setChecked(True)
        app.processEvents()
        if not win.tab_current('profile_tab') or not win.canvas.line_mode:
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
        # zoom: Cmd/Ctrl + drag up zooms in around the press point, [ ] step
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QWheelEvent
        win.canvas.fit()
        s0 = win.canvas.transform().m11()
        QTest.mousePress(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, c)
        QTest.mouseMove(vp, c - QPoint(0, 120))
        QTest.mouseRelease(vp, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier,
                           c - QPoint(0, 120))
        s1 = win.canvas.transform().m11()
        if not s1 > s0 * 1.2:
            raise AssertionError(f'Cmd+drag zoom: {s0:.3f} -> {s1:.3f}')
        win.canvas.zoom_by(1 / 1.25)
        if abs(win.canvas.transform().m11() - s1 / 1.25) > 1e-6:
            raise AssertionError('[ zoom out')
        # the plain wheel moves through time (one step per notch), not the zoom
        t_before, s2 = win.current.t, win.canvas.transform().m11()

        def wheel(dy):
            ev = QWheelEvent(QPointF(c), QPointF(vp.mapToGlobal(c)), QPoint(0, 0), QPoint(0, dy),
                             Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                             Qt.ScrollPhase.NoScrollPhase, False)
            QApplication.sendEvent(vp, ev)
            app.processEvents()

        wheel(-120)
        if win.current.t != min(t_before + 1, win.current.nt - 1) \
                or win.canvas.transform().m11() != s2:
            raise AssertionError(f'wheel: t {t_before} -> {win.current.t}')
        wheel(120)
        if win.current.t != t_before:
            raise AssertionError('wheel back')
        # feature-menu tabs: open next to LUT / 이미지 정보 in menu order, close again
        win.hide_tab('profile_tab')
        win.tool_actions['crop_tab'].setChecked(True)
        win.tool_actions['coloc_tab'].setChecked(True)
        tabs = [win.right_tabs.tabText(i) for i in range(win.right_tabs.count())]
        if tabs[:3] != ['LUT', '이미지 정보', 'Crop'] or 'Coloc 2' not in tabs \
                or '라인 프로파일' in tabs or not win.tab_current('coloc_tab'):
            raise AssertionError(f'menu tabs: {tabs}')
        win.tool_actions['coloc_tab'].setChecked(False)
        if win.tab_open('coloc_tab'):
            raise AssertionError('menu did not close the tab')
        # one menu per feature next to 파일; the markers sit fixed in the LUT tab
        menus = [a.text() for a in win.menuBar().actions()]
        want = ['파일', 'LUT', '마커', 'Crop', '세포질 ROI', '입자 ROI', '강도 측정', 'Coloc 2',
                '라인 프로파일', '스택', '이미지 정보', 'Figure']
        if menus != want or 'marker_tab' in win.tab_pages:
            raise AssertionError(f'menus: {menus}')
        lut_page = win.right_tabs.widget(0)
        if not lut_page.isAncestorOf(win.markers):
            raise AssertionError('markers are not in the LUT tab')
        # marker settings: save, change, load back (also through 불러오기)
        import json as _json
        win.markers.sb_len.setValue(7.5)
        win.markers.ts_prefix.setText('t=')
        mpath = out / 'markers.json'
        mpath.write_text(_json.dumps({'format': 'cytosol-viewer-markers', 'version': 1,
                                      'state': __import__('cytosol.project', fromlist=['x'])
                                      .widget_state(win.markers)}))
        win.markers.sb_len.setValue(0)
        win.markers.ts_prefix.setText('')
        if not win._is_marker_file(mpath) or win._is_preset(mpath):
            raise AssertionError('marker file detection')
        win.import_paths([mpath])
        if win.markers.sb_len.value() != 7.5 or win.markers.ts_prefix.text() != 't=':
            raise AssertionError('marker settings not loaded')
        win.markers.sb_len.setValue(0)
        win.markers.ts_prefix.setText('')
        # project file: everything back after closing the work
        from .cellroi import CellRois
        from .intensity import ParticleSettings
        it = win.current
        h, w = it.image.shape[-2:]
        lab = np.zeros((h, w), np.int32)
        lab[5:30, 5:30], lab[30:55, 30:60] = 1, 2
        it.cells = CellRois(lab, None, it.pixel_um, {1: 'ok', 2: 'edge'}, saturation=1.39)
        it.crops = [(2, 3, 20, 25)]
        it.group = 'grp'
        it.luts[1].vmax = 1234.5
        it.particle_settings = ParticleSettings(channel=it.channels[1], k=2.5)
        win.intensity_panel.expr.setText('cyto - particle')
        win.particle_panel.measure.batch_rows = [{'image': it.label, 'value': 1.5}]
        win.statusBar().showMessage('selftest step')
        n_coloc = len(it.coloc)
        win.open_figure()
        win.figure_win.spec.cells[0][0].item = it
        win.figure_win.spec.cells[0][0].region = (2, 3, 20, 25)
        win.figure_win.close()
        proj = out / 'selftest.cyproj'
        win.write_project_to(proj)
        n_log = len(win.worklog.entries)
        win.dirty = False
        win.new_project()
        if win.items or win.tab_open('coloc_tab') is None:
            raise AssertionError('new project left images')
        if not win.open_project(proj):
            raise AssertionError('project did not open')
        it = win.current
        if len(win.items) != 1 or it is None or it.image_id != win.items[0].image_id:
            raise AssertionError('project images')
        if not np.array_equal(it.cells.labels, lab) or it.cells.status != {1: 'ok', 2: 'edge'} \
                or it.cells.saturation != 1.39:
            raise AssertionError('project cell ROIs')
        if it.crops != [(2, 3, 20, 25)] or it.group != 'grp' or it.luts[1].vmax != 1234.5:
            raise AssertionError(f'project image settings {it.crops} {it.group} {it.luts[1].vmax}')
        if it.particle_settings is None or it.particle_settings.k != 2.5:
            raise AssertionError('project particle settings')
        if len(it.coloc) != n_coloc or win.intensity_panel.expr.text() != 'cyto - particle':
            raise AssertionError('project Coloc 2 results / tab settings')
        if win.particle_panel.measure.batch_rows != [{'image': it.label, 'value': 1.5}]:
            raise AssertionError('project measurement table')
        if not win.tab_open('crop_tab') or win.tab_open('coloc_tab'):
            raise AssertionError(f'project tabs {win.open_tabs()}')
        if len(win.worklog.entries) < n_log or not any(
                e['action'] == 'selftest step' for e in win.worklog.entries):
            raise AssertionError('project work log')
        fig = win.figure_win.spec.cells[0][0] if win.figure_win is not None else None
        if fig is None or fig.item is not it or fig.region != (2, 3, 20, 25):
            raise AssertionError('project figure')
        win.figure_win.deleteLater()
        win.figure_win = None
        # 불러오기: saved ROI / crop files recognised and put back on the image
        from .crops import save_crop_rois
        rz = out / 'import' / 'roundtrip_RoiSet.zip'
        it.cells.save(rz, properties=it.id_properties())
        cz = save_crop_rois(out / 'import' / 'roundtrip_crops.zip', it.crops, it.id_properties())
        it.cells, it.crops = None, []
        win.import_paths([rz, Path(cz)])
        if it.cells is None or len(it.cells) != 2 or it.crops != [(2, 3, 20, 25)]:
            raise AssertionError('불러오기 did not restore ROIs / crops')
        it.cells, it.crops, it.particle_settings, it.group = None, [], None, ''
        win.particle_panel.spot_k.setValue(3.0)
        win.intensity_panel.expr.setText('')
        win._groups_changed()
        win.particle_panel.bind(it)
        win.roi_panel.bind(it)
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
        # Figure window: each cell gets its own channel combination
        win.open_figure()
        fw = win.figure_win
        fw.table.setCurrentCell(0, 0)
        fw.src_combo.setCurrentIndex(fw.src_combo.findData(win.items.index(win.current)))
        cell = fw.current_cell()
        if cell.channels is not None or len(fw.chan_checks) != len(win.current.channels):
            raise AssertionError('figure cell channel checkboxes')
        fw._set_all_channels(False)
        fw.chan_checks[-1].setChecked(True)
        if cell.channels != [len(win.current.channels) - 1] or fw.merged_chk.isChecked():
            raise AssertionError(f'figure cell channel pick: {cell.channels}')
        fw.merged_chk.setChecked(True)
        if cell.channels is not None:
            raise AssertionError('figure cell did not go back to the main window channels')
        # inset region: .roi round trip and copy / paste into another cell
        from .figure import FigureCell, Inset, read_inset_rois, write_inset_rois

        cell.insets = [Inset((4, 5, 20, 21))]
        fw._refresh_inset_list(select=0)
        write_inset_rois(out / 'selftest_inset.roi', [(4, 5, 20, 21)])
        if read_inset_rois(out / 'selftest_inset.roi') != [(4, 5, 20, 21)]:
            raise AssertionError('inset .roi round trip')
        fw._copy_inset()
        fw.spec.add_col()
        other = fw.spec.cells[0][-1]
        other.copy_from(FigureCell(item=win.current))
        fw.rebuild_table()
        if fw._inset_clip is None:
            raise AssertionError('inset copy')
        fw.table.setCurrentCell(0, fw.spec.ncols - 1)
        fw._paste_inset()
        if [i.rect for i in other.insets] != [(4, 5, 20, 21)]:
            raise AssertionError(f'inset paste: {[i.rect for i in other.insets]}')
        # drag a box to move it; one box size for every image
        fw._inset_moved(0, 3, -2)
        if other.insets[0].rect != (7, 3, 23, 19):
            raise AssertionError(f'inset move: {other.insets[0].rect}')
        fw.box_w.setValue(10)
        fw.box_h.setValue(8)
        fw._size_to_all()
        sizes = {(x1 - x0, y1 - y0) for c in (cell, other) for x0, y0, x1, y1 in
                 (i.rect for i in c.insets)}
        if sizes != {(10, 8)} or other.insets[0].rect != (10, 7, 20, 15):
            raise AssertionError(f'inset size to all: {sizes}, {other.insets[0].rect}')
        if fw.cell_canvas.crop_size != (10, 8):
            raise AssertionError('fixed-size drawing not switched on')
        fw.close()
        # every ROI tab measures and follows ROI edits; particles from their own tab
        from .cellroi import segment_cells
        own = _synthetic_item()
        p0 = own.planes()
        own.cells = segment_cells(p0[1], p0[0], own.pixel_um)
        own.cells.renumber()
        win._add_item(own)
        win.file_list.setCurrentRow(len(win.items) - 1)
        win.show_tab('roi_tab')
        app.processEvents()
        cm = win.roi_panel.measure
        cm.refresh(force=True)
        if len(cm.rows) != 3 * len(own.cells):
            raise AssertionError(f'cell intensity rows {len(cm.rows)} for {len(own.cells)} cells')
        # 세포질 ROI: hover label, 자동 fields hold the values in use, 수동 mode,
        # size range estimated from every image
        rp = win.roi_panel
        rp.draw_overlay()
        l1 = own.cells.ids()[0]
        hx, hy = own.cells.centroid(l1)
        info = rp.hover_info(hx, hy)
        if not info or not info[0].startswith(f'cell{l1:03d}') or 'µm²' not in info[0]:
            raise AssertionError(f'ROI hover label: {info}')
        rp.show_auto_values(own)
        if not rp.sat_auto.isChecked() or rp.sat.value() <= 0 or rp.sat.isEnabled():
            raise AssertionError('automatic saturation not shown in its field')
        auto_thr = rp._auto_thresholds(own)['cell']
        if abs(rp.thr['cell']['spin'].value() - auto_thr) > 0.01:
            raise AssertionError('automatic cell threshold not shown in its field')
        rp.mode_tabs.setCurrentIndex(1)
        rp.man['cell']['spin'].setValue(30)
        man = rp._detect(own, rp.roles(own))
        if (man.labels > 0).sum() != ndi_fill(own.planes()[rp.roles(own)['bg']] >= 30).sum():
            raise AssertionError('수동 mode is not "at or above the threshold"')
        rp.mode_tabs.setCurrentIndex(0)
        # live preview: a background detection drawn instead of the ROIs
        import time as _time
        rp.live.setChecked(True)
        rp._live_timer.stop()
        rp._live_start()
        t_end = _time.time() + 30
        while rp._live is None and _time.time() < t_end:
            app.processEvents()
            _time.sleep(0.02)
        if rp._live is None or rp._hover_rois is not rp._live[1]:
            raise AssertionError('live preview did not show a detection')
        rp.min_cell.setValue(120)  # a slider under the field follows it
        if rp._size_sliders[rp.min_cell].value() <= 0:
            raise AssertionError('size slider did not follow its field')
        rp.live.setChecked(False)
        rp._live_timer.stop()
        if rp._live is not None:
            raise AssertionError('live preview not cleared when switched off')
        rp.size_auto.setChecked(True)
        if rp.min_cell.isEnabled() or not 50 < rp.min_cell.value() <= rp.max_cell.value():
            raise AssertionError(f'size range estimate {rp.min_cell.value()}–{rp.max_cell.value()}')
        rp.size_auto.setChecked(False)
        rp.min_cell.setValue(80)
        rp.max_cell.setValue(0)
        rp.min_nuc.setValue(15)
        rp.max_nuc.setValue(0)
        rp.man['cell']['spin'].setValue(0)
        win.show_tab('particle_tab')
        pp = win.particle_panel
        pp.part_channel.setCurrentIndex(1)
        pp.part_on.setChecked(True)
        pp.refresh()
        pp.measure.refresh(force=True)
        if own.particle_settings is None or own.particles is None:
            raise AssertionError('particle ROIs not defined from the panel')
        if pp.contour_value() != 0.5 or win.canvas._contour_item is None:
            raise AssertionError('iso-contour shape not on by default or not drawn')
        if pp.intensity_value() is not None:
            raise AssertionError('intensity not on pixel ROIs by default')
        pix = {r['roi']: r['area_px'] for r in pp.measure.rows if r['region'] == 'particle'}
        pp.int_contour.setChecked(True)
        pp.measure.refresh(force=True)
        iso = [r for r in pp.measure.rows if r['region'] == 'particle']
        if not iso or any(r.get('particle_intensity_roi') != 'iso-contour 0.5'
                          or r['area_px'] > pix[r['roi']] for r in iso):
            raise AssertionError(f'contour intensity rows {iso[:1]}')
        pp.int_pixel.setChecked(True)
        pp.measure.refresh(force=True)
        if len(pp.measure.rows) != 2 * len(own.cells) \
                or 'n_particles' not in pp.measure.rows[0]:
            raise AssertionError(f'particle rows: {len(pp.measure.rows)}')
        win.show_tab('intensity_tab')
        ip = win.intensity_panel
        ip.expr.setText('cyto - particle; cell & particle')
        ip.measure.refresh(force=True)
        ip.draw_regions()
        if len(ip.measure.rows) != 2 * len(own.cells):
            raise AssertionError(f'logic rows: {len(ip.measure.rows)}')
        if win.canvas._logic_item is None:
            raise AssertionError('logic regions not drawn')
        win.roi_panel.select(own.cells.ids()[0])
        win.roi_panel.delete_selected()
        ip.measure.refresh()
        if len(ip.measure.rows) != 2 * len(own.cells):
            raise AssertionError('intensity did not follow the deleted cell')
        for box in win._measure_boxes():
            res = box.measure_items(win.items)
            if not res.get(id(own)):
                raise AssertionError(f'{box.suffix}: all-image measurement skipped the image')
            box.save_item(own, out / 'intensity_gui', res[id(own)])
        from .lut import item_stem
        stem = item_stem(own)
        for name in ('cell_intensity.csv', 'particle_intensity.csv', 'intensity.csv',
                     'RoiSet.zip', 'particles.zip', 'particles_contour.zip', 'regions.zip',
                     'image.png'):
            if not (out / 'intensity_gui' / f'{stem}_{name}').exists():
                raise AssertionError(f'missing {stem}_{name}')
        # user-named groups: group column, per-image / per-group summaries, saved and restored
        from .groups import GROUP_FILE, apply_groups, read_groups, summarize, write_groups
        win.set_group([own], 'ctrl')
        leaf = win.file_list.item(win.items.index(own))
        if leaf.text(0) != own.label or leaf.parent() is None or not leaf.parent().text(0).startswith('ctrl'):
            raise AssertionError('group not shown as a folder in the list')
        from .groups import auto_groups, suggest_name
        if suggest_name(['abc', 'abc_0001', 'abc_0002.tif']) != 'abc' \
                or auto_groups(['abc', 'abc_0001', 'x', 'abc_0002']) != {0: 'abc', 1: 'abc', 3: 'abc'}:
            raise AssertionError('group name from file names')
        pm = pp.measure
        pm.batch_rows = [r for rs in pm.measure_items([own]).values() for r in rs]
        if not pm.batch_rows or pm.batch_rows[0].get('group') != 'ctrl':
            raise AssertionError('no group column in particle rows')
        win.set_group([own], 'treated')
        if pm.batch_rows[0]['group'] != 'treated':
            raise AssertionError('rows did not follow the renamed group')
        summ = summarize(pm.batch_rows, False)
        mean = [r for r in summ if r['parameter'] == 'n_particles' and r['region'] == 'particle']
        vals = [r['n_particles'] for r in pm.batch_rows if r['region'] == 'particle']
        if len(mean) != 1 or mean[0]['group'] != 'treated' or mean[0]['n'] != len(vals) \
                or abs(mean[0]['mean'] - np.mean(vals)) > 1e-6 or mean[0]['max'] != max(vals):
            raise AssertionError(f'group summary: {mean}')
        pm.view.setCurrentIndex(pm.view.findData('sum_group'))
        if pm.table.rowCount() != len(summ):
            raise AssertionError('summary not shown')
        files = pm.write_summaries(out / 'intensity_gui', pm.batch_rows)
        if len(files) != 2:
            raise AssertionError(f'summary files {files}')
        write_groups(out / 'intensity_gui' / GROUP_FILE, win.items)
        own.group = ''
        if apply_groups(win.items, read_groups(out / 'intensity_gui' / GROUP_FILE)) != 1 \
                or own.group != 'treated':
            raise AssertionError('groups not restored')
        win.set_group([own], '')
        pm.view.setCurrentIndex(0)
        # particles over the whole image of an image without cell ROIs
        bare = _synthetic_item()
        win._add_item(bare)
        win.file_list.setCurrentRow(len(win.items) - 1)
        win.show_tab('particle_tab')
        app.processEvents()
        if pp.within.currentData() != 'image':
            raise AssertionError('whole image not preselected without cell ROIs')
        pp.part_channel.setCurrentIndex(1)
        pp.part_on.setChecked(True)
        pp.refresh()
        pp.measure.refresh(force=True)
        if bare.particles is None or not bare.particles.mask.any():
            raise AssertionError('no particles over the whole image')
        if len(pp.measure.rows) != 2 or pp.measure.rows[0]['roi'] != 'image':
            raise AssertionError(f'whole-image particle rows: {pp.measure.rows}')
        res = pp.measure.measure_items(win.items)
        if not res.get(id(bare)) or not res.get(id(own)):
            raise AssertionError('all-image particle measurement skipped an image')
        pp.measure.save_item(bare, out / 'particles_whole', res[id(bare)])
        if not (out / 'particles_whole' / f'{item_stem(bare)}_particles.zip').exists():
            raise AssertionError('whole-image particle ROIs not saved')
        # one row per particle, with shape
        pp.per_particle.setChecked(True)
        pp.measure.refresh(force=True)
        n_part = sum(bare.particles.counts(pp.cells_for(bare)).values())
        if len(pp.measure.rows) != n_part or 'circularity' not in pp.measure.rows[0] \
                or pp.measure.rows[0]['roi'] != 'image':
            raise AssertionError(f'per-particle rows {len(pp.measure.rows)} for {n_part}')
        res = pp.measure.measure_items([own, bare])
        pp.measure.save_item(own, out / 'particles_shape', res[id(own)])
        if not (out / 'particles_shape' / f'{item_stem(own)}_particle_shape.csv').exists():
            raise AssertionError('per-particle CSV not saved')
        pp.per_cell.setChecked(True)
        from .intensity import is_particle_file, is_region_file
        rz = out / 'intensity_gui' / f'{stem}_regions.zip'
        if not is_region_file(rz) or is_particle_file(rz):
            raise AssertionError('region ROI file not recognised')
        # multi-select removal
        win.add_files([out / 'selftest.TCF'])
        win.add_files([out / 'selftest.TCF'])
        n = len(win.items)
        win.apply_auto_groups({'tcf': win.items[-2:]})
        folder = win.file_list.item(n - 1).parent()
        win.file_list.clearSelection()
        folder.setSelected(True)
        if win.file_list.selected_rows() != [n - 2, n - 1] or win.file_list.selected_group() != 'tcf':
            raise AssertionError('group folder selection')
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

    def bleach_info():
        from .imageinfo import (czi_bleach_info, czi_bleach_rois, is_bleach_file,
                                load_bleach_rois, summarize)
        from .lut import ImageItem, export_item
        from .render import OutlineStyle
        xml = ('<ImageDocument><Metadata><Experiment><BleachingSetup IsActivated="true">'
               '<ExtensionSettings><Iterations>2</Iterations></ExtensionSettings></BleachingSetup>'
               '<TimelineElement Id="1"><Duration>0.2</Duration><EventInformation><Bleaching>'
               '<BleachingType>TimedBleaching</BleachingType><BleachingRegions><BleachRegion>'
               '<Name>Region 1</Name><BleachRegionGeometryString>F1M60,40C71,40 80,49 80,60'
               'C80,71 71,80 60,80 49,80 40,71 40,60 40,49 49,40 60,40z</BleachRegionGeometryString>'
               '<Laserlines><Laserline><Wavelength>405</Wavelength><Intensity>10</Intensity>'
               '</Laserline></Laserlines></BleachRegion></BleachingRegions></Bleaching>'
               '</EventInformation><Bounds StartT="3" /></TimelineElement></Experiment>'
               '</Metadata></ImageDocument>')
        rois = czi_bleach_rois(xml)
        info = czi_bleach_info(xml, [(1.0, 'BLEACH_START'), (1.2, 'BLEACH_STOP')],
                               [0.0, 0.5, 0.9, 1.3, 1.8])
        x0, y0, x1, y1 = rois[0].bounds()
        if len(rois) != 1 or abs(x0 - 40) > 0.5 or abs(y1 - 80) > 0.5 or rois[0].lasers != [(405.0, 10.0)]:
            raise AssertionError(f'bleach ROI parse: {rois}')
        if info['frames_after'] != [3] or info['count'] != 1:
            raise AssertionError(f'bleach events: {info}')
        it = ImageItem(path=item.path, image=item.image, label='bleach')
        it.luts = item.luts
        it.bleach_rois = rois
        rgb = it.decorate(it.composite(), outline=OutlineStyle(color=(1, 1, 0), thickness_px=2))
        if not ((rgb[..., 0] > 0.9) & (rgb[..., 1] > 0.9) & (rgb[..., 2] < 0.1)).any():
            raise AssertionError('bleach outline not drawn')
        files = export_item(it, out / 'export_bleach', crops=False, raw_stack=False)
        zips = [f for f in files if f.endswith('_bleach_rois.zip')]
        if not zips or not is_bleach_file(zips[0]) or len(load_bleach_rois(zips[0])) != 1:
            raise AssertionError(f'bleach ROI file: {files}')
        s = summarize(it)
        if not any(sec == 'Bleach ROI' for sec, _, _ in s.general):
            raise AssertionError('bleach ROI missing from the summary')
        return f'{len(s.general)} info rows, {Path(zips[0]).name}'

    step('readers import', readers)
    step('HDF5 non-ASCII path', hdf5_unicode_path)
    step('TIFF export', tiff_export)
    step('time-series export', time_series_export)
    step('MP4 (odd frame size)', mp4_odd_size)
    step('line profile', line_profile_step)
    step('cell ROIs + RoiSet.zip', cell_rois)
    step('cell size range + manual threshold', cell_size_range)
    step('Coloc 2 per cell ROI', coloc2)
    step('intensity + particle ROIs', intensity)
    step('image ID in exports + pairing', image_id_pairing)
    step('same-name images, separate folders', same_name_export)
    step('figure export', figure)
    step('lazy TCF planes', lazy_tcf)
    step('time-series read-ahead', read_ahead)
    step('Z-stack projections', projections)
    step('bleach ROIs + image info', bleach_info)
    step('main window', window)

    text = '\n'.join(log) + f'\n\n{"PASSED" if ok else "FAILED"}\n'
    (out / 'selftest.log').write_text(text, encoding='utf-8')
    if sys.stdout is not None:
        print(text)
    return 0 if ok else 1


if __name__ == '__main__':
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else 'selftest-out'))
