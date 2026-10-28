"""Compare cytosol.frap with ImageJ: ROI means (OvalRoi / PolygonRoi masks,
Measure Mean) on a random stack, and the "Exponential recovery" fit
(CurveFitter.EXP_RECOVERY) on synthetic recovery curves.

    python scripts/imagej_reference/compare_frap.py CLASSPATH
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cytosol import frap  # noqa: E402
from cytosol.frap import FrapRoi  # noqa: E402


def run(cp, *args):
    out = subprocess.run(['java', '-cp', cp, 'FrapReference', *map(str, args)],
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def main():
    cp = sys.argv[1]
    rng = np.random.default_rng(5)
    T, H, W = 6, 120, 140
    stack = (rng.random((T, H, W)) * 1000).astype('<f4')
    tmp = Path(tempfile.mkdtemp())
    stack.tofile(tmp / 'stack.f32')
    rois = [FrapRoi('oval', 3, 4, 7, 7), FrapRoi('oval', 10, 20, 7, 12), FrapRoi('oval', 50, 50, 2, 2),
            FrapRoi('oval', 80, 30, 15, 8), FrapRoi('oval', 3, 4, 1, 1)]
    for _ in range(6):
        c = rng.uniform(20, 100, 2)
        a = np.sort(rng.uniform(0, 2 * np.pi, 5))
        r = rng.uniform(5, 18, 5)
        rois.append(FrapRoi('polygon', xy=np.c_[c[0] + r * np.cos(a), c[1] + r * np.sin(a)]))
    specs = [f'oval:{r.x},{r.y},{r.w},{r.h}' if r.kind == 'oval'
             else 'poly:' + ','.join(f'{v:.9g}' for v in np.asarray(r.xy, np.float32).ravel())
             for r in rois]
    worst = 0.0
    for r, line in zip(rois, run(cp, tmp / 'stack.f32', T, H, W, *specs)):
        ij = np.array(line.split()[1:], float)
        worst = max(worst, float(np.max(np.abs(ij - frap.roi_means(stack, r)) / np.abs(ij))))
    print(f'ROI means: {len(rois)} ROIs, largest relative difference {worst:.2e}')
    worst = 0.0
    for a, k, c in ((0.6, 0.15, 0.1), (0.3, 0.02, 0.4), (0.9, 0.5, 0.05)):
        x = np.arange(25) * 2.0
        y = a * (1 - np.exp(-k * x)) + c + rng.normal(0, 0.01, x.size)
        np.savetxt(tmp / 'x.txt', x)
        np.savetxt(tmp / 'y.txt', y)
        p = [float(v) for v in run(cp, 'fit', tmp / 'x.txt', tmp / 'y.txt')[0].split()[1:4]]
        f = frap.fit_recovery(x, y)
        d = max(abs(f.a - p[0]) / abs(p[0]), abs(f.b - p[1]) / abs(p[1]), abs(f.c - p[2]) / abs(p[2]))
        worst = max(worst, d)
        print(f'fit a {f.a:.6g} / {p[0]:.6g}, k {f.b:.6g} / {p[1]:.6g}, c {f.c:.6g} / {p[2]:.6g}')
    print(f'fit: largest relative difference {worst:.2e}')


if __name__ == '__main__':
    main()
