"""Whole-cell movie (green / Cy5 / RI crops + the cell's green curve) for chosen cells.

usage: python scripts/cell_movie.py PROJECT.cyproj LOCAL_BG_CSV OUT IMAGE::CELL [IMAGE::CELL ...]
Crops follow the cell's bounding box (union over frames, + 3 µm), cell outline from ParticleTracker's cell labels.
Green shown 0–6 (raw 8-bit counts), Cy5 auto (0.5–99.8 % of the crops), RI 0.5–99.8 %.
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

proj, lbcsv, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
want = {}
for s in sys.argv[4:]:
    img, c = s.split('::')
    want.setdefault(img, []).append(int(c))
out.mkdir(parents=True, exist_ok=True)
style.setup()
LB = pd.read_csv(lbcsv)
data, files = read_project(proj)
for n, _ in enumerate(data.get('images') or []):
    key = f'images/{n}/tracks.pkl'
    if key not in files:
        continue
    st = pickle.loads(files[key])
    pt = st.pt
    tcf, ref_ch = pt['sources']['reference'].rsplit('::', 1)
    name = Path(tcf).stem.split('.A1.')[-1]
    if name not in want:
        continue
    mea_ch = pt['sources']['measure'].rsplit('::', 1)[1]
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
        g = LB[(LB.image == name) & (LB.cell_id == c)].sort_values('frame')
        writer, ext = style.movie_writer(3, 3000)
        fig = plt.figure(figsize=(12, 7.4), dpi=80)
        axs = [fig.add_axes([.02 + i * .33, .40, .3, .52]) for i in range(3)]
        ax = fig.add_axes([.08, .07, .86, .25])
        ax.plot(g.t_h, g.green, '-', color='tab:green', label='green (세포 − 주변)')
        ax2 = ax.twinx()
        ax2.plot(g.t_h, g.cy5, '-', color='tab:red', label='Cy5 (세포 − 주변)')
        ax.set_xlabel('시간 (h)')
        ax.set_ylabel('green', color='tab:green')
        ax2.set_ylabel('Cy5', color='tab:red')
        vl = ax.axvline(0, color='k')
        path = out / f'cell_{name}_{c}{ext}'
        with writer.saving(fig, str(path), 80):
            for z in range(T):
                lab, hy, hx = labs[z]
                m = lab[y0:y1, x0:x1] == c
                h = HT[z][np.ix_(hy[y0:y1], hx[x0:x1])].astype(float)
                lo_h, hi_h = np.percentile(h, [.5, 99.8])
                for a, im, ttl, cmap, vmin, vmax in ((axs[0], cb[z], 'green (0–6)', 'Greens_r', 0, 6),
                                                    (axs[1], ca[z], 'Cy5', 'gray', lo_a, hi_a),
                                                    (axs[2], h, 'RI', 'gray', lo_h, hi_h)):
                    a.clear()
                    a.axis('off')
                    a.imshow(im, cmap='gray' if cmap == 'gray' else 'viridis' if False else cmap.replace('_r', ''),
                             vmin=vmin, vmax=vmax)
                    if m.any():
                        a.contour(m, [.5], colors='y', linewidths=.8)
                    a.set_title(ttl)
                vl.set_xdata([z * 20 / 60] * 2)
                fig.suptitle(f'{name} cell {c} | frame {z + 1} | t = {z * 20 / 60:.2f} h')
                writer.grab_frame()
        plt.close(fig)
        print('saved', path, flush=True)
    del A, B, HT, Bal
