"""Compare cytosol.coloc with Fiji's Coloc 2 code on synthetic data.

Needs the compiled Coloc 2 classes plus Coloc2Reference.class on the Java
classpath (see README in this folder):

    python scripts/imagej_reference/compare_coloc2.py CLASSPATH [OUT_DIR] [--no-costes]

Prints, per test case, every value Coloc 2 reports next to ours and the
largest relative difference; Costes values are random in both programs and
are compared over many randomisations instead.
"""

import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from cytosol.coloc import REGRESSIONS, Coloc2Settings, ValueType, run_coloc2  # noqa: E402


def cases():
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:180, 0:200]
    blob = np.exp(-(((yy - 90) / 40) ** 2 + ((xx - 100) / 55) ** 2))
    spots = np.zeros((180, 200))
    for _ in range(60):
        cy, cx = rng.integers(20, 160), rng.integers(20, 180)
        spots += np.exp(-(((yy - cy) / 3) ** 2 + ((xx - cx) / 3) ** 2))
    cell = ((yy - 90) / 70) ** 2 + ((xx - 100) / 85) ** 2 < 1
    nuc = ((yy - 85) / 22) ** 2 + ((xx - 95) / 28) ** 2 < 1
    a = rng.poisson(20 + 400 * blob + 1500 * spots).astype(np.uint16)
    b = rng.poisson(10 + 200 * blob + 900 * spots + 300 * rng.random(blob.shape)).astype(np.uint16)
    yield 'cell, uint16, Costes', a, b, cell, 'uint16', 'Costes'
    yield 'cytosol (hole), uint16, Bisection', a, b, cell & ~nuc, 'uint16', 'Bisection'
    neg = rng.poisson(30 + 600 * (1 - blob)).astype(np.uint16)
    yield 'anti-correlated, Costes', a, neg, cell, 'uint16', 'Costes'
    sat = np.minimum(a, 300).astype(np.uint16)
    zero = np.where(rng.random(a.shape) < 0.3, 0, b).astype(np.uint16)
    yield 'saturated + zeros, Bisection', sat, zero, cell, 'uint16', 'Bisection'
    fa = (a / 37.0).astype(np.float32)
    fb = (b / 11.0 + 0.25).astype(np.float32)
    yield 'float32, Bisection', fa, fb, cell, 'float', 'Bisection'
    z = np.stack([rng.poisson(20 + 300 * blob * s + 900 * spots) for s in (0.5, 1, 0.8)]).astype(np.uint16)
    z2 = np.stack([rng.poisson(10 + 200 * blob * s + 700 * spots) for s in (0.6, 1, 0.7)]).astype(np.uint16)
    yield '3D stack, 2D ROI through Z, Costes', z, z2, cell, 'uint16', 'Costes'
    real = Path(os.environ.get('COLOC2_REAL', '/nonexistent'))
    if (real / 'a.npy').exists():  # optional: a real image (a.npy, b.npy) and ROI masks.npz
        a, b = np.load(real / 'a.npy'), np.load(real / 'b.npy')
        masks = np.load(real / 'masks.npz')
        for name in sorted(masks.files):
            kind = {'uint8': 'uint8', 'uint16': 'uint16'}.get(str(a.dtype), 'float')
            for regr in REGRESSIONS:
                yield f'real image {name}, {regr}', a, b, masks[name], kind, regr


def java(cp, d, kind, regr, psf, nrand):
    out = subprocess.run(['java', '-cp', cp, 'Coloc2Reference', str(d), kind, regr, str(psf),
                          str(nrand)], capture_output=True, text=True, check=True).stdout
    vals, hists, warns = {}, {}, []
    for line in out.splitlines():
        f = line.split('\t')
        if f[0] == 'VAL':
            vals[f[1]] = f[2]
        elif f[0] == 'HIST':
            hists[f[1]] = (int(f[2]), int(f[3]))
        elif f[0] == 'WARN':
            warns.append(f[1])
    return vals, hists, warns


def write(d, a, b, mask):
    d.mkdir(parents=True, exist_ok=True)
    ys, xs = np.nonzero(mask)
    x0, y0 = xs.min(), ys.min()
    (d / 'bbox.txt').write_text(f'{x0} {y0} {xs.max() - x0 + 1} {ys.max() - y0 + 1}')
    dims = list(a.shape[::-1])
    (d / 'dims.txt').write_text(' '.join(map(str, dims)))
    m = np.broadcast_to(mask, a.shape).astype(np.uint8)
    for name, arr in (('a', a), ('b', b), ('mask', m)):
        arr.astype(arr.dtype.newbyteorder('<')).tofile(d / f'{name}.raw')


def main():
    cp = sys.argv[1]
    args = [a for a in sys.argv[2:] if not a.startswith('--')]
    root = Path(args[0]) if args else Path(tempfile.mkdtemp())
    worst = 0.0
    for i, (title, a, b, mask, kind, regr) in enumerate(cases()):
        d = root / f'case{i}'
        write(d, a, b, mask)
        jv, jh, jw = java(cp, d, kind, regr, 3, 0)
        s = Coloc2Settings(regression=regr, costes=False)
        vt = ValueType.for_dtype(a.dtype)
        r = run_coloc2(a, b, mask, s, vt, names=('A', 'B'))
        print(f'\n== {title}')
        for name, val, _ in r.values:
            if name not in jv or isinstance(val, str):
                continue
            j = float(jv[name])
            p = float(val)
            if math.isnan(j) and math.isnan(p):
                rel = 0.0
            else:
                rel = abs(p - j) / max(abs(j), 1e-12)
            worst = max(worst, rel)
            flag = '' if rel < 1e-9 else '   <-- differs'
            print(f'{name:45s} ImageJ {j:<22.12g} ours {p:<22.12g} rel.diff {rel:.1e}{flag}')
        for h in r.histograms:
            c = h.counts
            xs, ys = np.nonzero(c)
            w = int((c[xs, ys] * (xs * 1000 + ys)).sum())
            same = jh.get(h.title) == (int(c.sum()), w)
            print(f'histogram {h.title:28s} identical bins: {same}')
            worst = max(worst, 0.0 if same else 1.0)
        ours_w = [w for w, _ in r.warnings]
        print('warnings ImageJ:', jw, '\nwarnings ours:  ', ours_w)
    print(f'\nlargest relative difference (all non-random values): {worst:.2e}')

    # Costes: both programs shuffle at random, so compare the distribution of
    # the shuffled Pearson values over many randomisations
    title, a, b, mask, kind, regr = next(cases())
    d = root / 'case0'
    for psf in (3, 5):
        if '--no-costes' in sys.argv:
            break
        jv, _, _ = java(cp, d, kind, regr, psf, 200)
        s = Coloc2Settings(regression=regr, psf=psf, costes_randomisations=200)
        r = run_coloc2(a, b, mask, s, ValueType.for_dtype(a.dtype), names=('A', 'B'), seed=1)
        print(f'\nCostes (PSF {psf}, 200 randomisations)')
        for k in ('Costes Shuffled Mean', 'Costes Shuffled Std.D.', 'Costes P-Value'):
            print(f'{k:28s} ImageJ {float(jv[k]):.4f}   ours {r.value(k):.4f}')


if __name__ == '__main__':
    main()
