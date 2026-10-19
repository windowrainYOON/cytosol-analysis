"""Compare cytosol.intensity with ImageJ (IntensityReference.java): per-ROI
Otsu threshold (setAutoThreshold("Otsu dark")) and Measure values.

    python scripts/imagej_reference/compare_intensity.py CLASSPATH [plane.npy labels.npy bits]

Without arguments after CLASSPATH it runs synthetic 8/16/32-bit cases."""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cytosol.cellroi import CellRois  # noqa: E402
from cytosol.intensity import Region, measure_cells, otsu_thresholds  # noqa: E402


def imagej(cp, plane, labels, bits):
    with tempfile.TemporaryDirectory() as d:
        dt = {8: '<u1', 16: '<u2', 32: '<f4'}[bits]
        plane.astype(dt).tofile(f'{d}/p.raw')
        labels.astype('<i4').tofile(f'{d}/l.raw')
        h, w = plane.shape
        out = subprocess.run(['java', '-cp', cp, 'IntensityReference', f'{d}/p.raw', str(w),
                              str(h), str(bits), f'{d}/l.raw'], capture_output=True, text=True,
                             check=True).stdout
    rows = {}
    for line in out.split():
        l, thr, n, mean, sd, mn, mx = line.split(',')
        rows[int(l)] = (float(thr), int(n), float(mean), float(sd), float(mn), float(mx))
    return rows


def compare(cp, plane, labels, bits, name):
    dtype = {8: np.uint8, 16: np.uint16, 32: np.float32}[bits]
    plane = plane.astype(dtype)
    ref = imagej(cp, plane, labels, bits)
    p = plane.astype(np.float32)
    ours_thr = otsu_thresholds(p, labels, labels > 0, bits)
    cells = CellRois(labels.astype(np.int32))
    rows = measure_cells(p[None], cells, [Region('cell', ('name', 'cell'))], ['c'], None,
                         stats=('Mean', 'StdDev', 'Min', 'Max'))
    worst = dict(thr=0.0, mean=0.0, sd=0.0, minmax=0.0, n=0)
    for row in rows:
        l = int(row['roi'][4:])
        thr, n, mean, sd, mn, mx = ref[l]
        worst['thr'] = max(worst['thr'], abs(ours_thr[l] - thr) / max(abs(thr), 1e-9))
        worst['n'] = max(worst['n'], abs(row['area_px'] - n))
        worst['mean'] = max(worst['mean'], abs(row['c_Mean'] - mean) / max(abs(mean), 1e-9))
        worst['sd'] = max(worst['sd'], abs(row['c_StdDev'] - sd) / max(abs(sd), 1e-9))
        worst['minmax'] = max(worst['minmax'], abs(row['c_Min'] - mn), abs(row['c_Max'] - mx))
    print(f'{name}: {len(rows)} ROIs, max relative diff threshold {worst["thr"]:.2e}, '
          f'mean {worst["mean"]:.2e}, StdDev {worst["sd"]:.2e}; '
          f'max |min/max diff| {worst["minmax"]:.3g}; pixel count diff {worst["n"]}')
    return worst


def synthetic(seed):
    rng = np.random.default_rng(seed)
    h, w = 180, 240
    labels = np.zeros((h, w), np.int32)
    yy, xx = np.mgrid[:h, :w]
    for l, (cy, cx, r) in enumerate([(50, 60, 35), (60, 170, 40), (135, 110, 38)], 1):
        labels[(yy - cy) ** 2 + (xx - cx) ** 2 < r * r] = l
    base = rng.gamma(2.0, 1.0, (h, w))
    spots = np.zeros((h, w))
    for _ in range(40):
        y, x = rng.integers(0, h), rng.integers(0, w)
        spots += 8 * np.exp(-((yy - y) ** 2 + (xx - x) ** 2) / 6)
    return base + spots, labels


def main():
    cp = sys.argv[1]
    if len(sys.argv) > 4:
        plane, labels = np.load(sys.argv[2]), np.load(sys.argv[3])
        compare(cp, plane, labels, int(sys.argv[4]), Path(sys.argv[2]).stem)
        return
    for seed in range(3):
        img, labels = synthetic(seed)
        compare(cp, np.clip(img * 12, 0, 255), labels, 8, f'8-bit seed {seed}')
        compare(cp, img * 300 + 100, labels, 16, f'16-bit seed {seed}')
        compare(cp, img * 0.37 - 1.5, labels, 32, f'32-bit seed {seed}')


if __name__ == '__main__':
    main()
