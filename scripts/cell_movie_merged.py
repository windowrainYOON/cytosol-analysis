"""Merged whole-cell movies: RI (gray) + Cy5 (magenta) + pHrodo (green) in one crop per cell.

usage: python scripts/cell_movie_merged.py PROJECT.cyproj OUT CELLS_CSV|IMAGE::CELL ...
Crop = the cell's bounding box over all frames + 3 µm; yellow line = the cell outline (ParticleTracker cell labels).
Display: pHrodo 0–6 (raw 8-bit), Cy5 0.5–99.8 % of the crop over time, RI 0.5–99.8 % (dimmed to 60 %).
MP4 at 3 frames/s with the time stamp.
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from cytosol import pt_engine  # noqa: E402
from cytosol.project import read_project  # noqa: E402
from cytosol.ptcore import registration, style  # noqa: E402

proj, out = Path(sys.argv[1]), Path(sys.argv[2])
want = {}
for s in sys.argv[3:]:
    names = list(pd.read_csv(s).cell) if s.endswith('.csv') else [s]
    for u in names:
        img, c = u.split('::')
        want.setdefault(img, []).append(int(c))
out.mkdir(parents=True, exist_ok=True)
style.setup()


def scale(im, lo, hi):
    return np.clip((im - lo) / (hi - lo if hi > lo else 1), 0, 1)


data, files = read_project(proj)
for n, _ in enumerate(data.get('images') or []):
    key = f'images/{n}/tracks.pkl'
    if key not in files:
        continue
    pt = pickle.loads(files[key]).pt
    tcf, ref_ch = pt['sources']['reference'].rsplit('::', 1)
    name = Path(tcf).stem.split('.A1.')[-1]
    if name not in want:
        continue
    mea_ch = pt['sources']['measure'].rsplit('::', 1)[1]
    dt = float((pt.get('cfg') or {}).get('channel', {}).get('frame_interval_min', 20.0))
    CID, reg, S = pt_engine._unpack(pt['arrays'])['CID'], pt['reg'], float(pt['S'])
    A, B, HT = pt_engine.load(tcf, ref_ch, mea_ch)
    Bal = registration.align_b(B, reg)
    T, NF, NW = A.shape
    NH, NHW = CID.shape[1:]
    yy, xx = np.arange(NF), np.arange(NW)
    labs = []
    for z in range(T):
        hy = np.clip(np.round((yy + .5) * S - .5 + reg.dy_ht.values[z]).astype(int), 0, NH - 1)
        hx = np.clip(np.round((xx + .5) * S - .5 + reg.dx_ht.values[z]).astype(int), 0, NHW - 1)
        labs.append((CID[z][np.ix_(hy, hx)], hy, hx))
    for c in want[name]:
        ys, xs = [], []
        for lab, _, _ in labs:
            r, q = np.nonzero(lab == c)
            if len(r):
                ys += [r.min(), r.max()]
                xs += [q.min(), q.max()]
        pad = int(3 / 0.1125)
        y0, y1 = max(min(ys) - pad, 0), min(max(ys) + pad, NF)
        x0, x1 = max(min(xs) - pad, 0), min(max(xs) + pad, NW)
        ca = A[:, y0:y1, x0:x1].astype(float)
        cb = Bal[:, y0:y1, x0:x1].astype(float)
        lo_a, hi_a = np.percentile(ca, [.5, 99.8])
        h_all = np.stack([HT[z][np.ix_(labs[z][1][y0:y1], labs[z][2][x0:x1])] for z in range(T)]).astype(float)
        lo_h, hi_h = np.percentile(h_all, [.5, 99.8])
        hgt, wid = y1 - y0, x1 - x0
        fig = plt.figure(figsize=(7, 7 * hgt / wid + .5), dpi=100)
        ax = fig.add_axes([0, 0, 1, hgt / (hgt + .5 * wid / 7)])
        writer, ext = style.movie_writer(3, 4000)
        path = out / f'merged_{name}_cell{c}{ext}'
        with writer.saving(fig, str(path), 100):
            for z in range(T):
                ri = .6 * scale(h_all[z], lo_h, hi_h)
                cy = scale(ca[z], lo_a, hi_a)
                ph = scale(cb[z], 0, 6)
                rgb = np.clip(np.stack([ri + cy, ri + ph, ri + cy], -1), 0, 1)
                ax.clear()
                ax.axis('off')
                ax.imshow(rgb)
                m = labs[z][0][y0:y1, x0:x1] == c
                if m.any():
                    ax.contour(m, [.5], colors='y', linewidths=.8)
                ax.text(.02, .97, f'{name} cell {c}   t = {z * dt / 60:.2f} h', transform=ax.transAxes, color='w',
                        va='top', fontsize=11)
                ax.text(.02, .03, 'RI (gray)  Cy5 (magenta)  pHrodo (green)', transform=ax.transAxes, color='w',
                        fontsize=9)
                bar = 10 / 0.1125
                ax.plot([wid - bar - 10, wid - 10], [hgt - 12, hgt - 12], color='w', lw=3)
                ax.text(wid - bar / 2 - 10, hgt - 18, '10 µm', color='w', ha='center', fontsize=9)
                writer.grab_frame()
        plt.close(fig)
        print('saved', path.name, flush=True)
    del A, B, HT, Bal
