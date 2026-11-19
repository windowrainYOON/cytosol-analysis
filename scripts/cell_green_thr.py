"""Per-cell green after dropping every pixel at or below an early-time threshold (owner 2026-11-19).

usage: python scripts/cell_green_thr.py PROJECT.cyproj LOCAL_BG_CSV OUT [early_min=100] [percentile=50]
Threshold T of an image = the given percentile (default 50 = median) of all green (measure) pixels of its frames in 0–early_min minutes (the green
floor while the medium green settles).  Pixels <= T are set to 0; no background is subtracted.  Per cell and frame:
  green_thr       mean over the cell of the kept pixels (0 elsewhere)
  green_excess    mean over the cell of max(green − T, 0)
  green_pos_frac  fraction of the cell's pixels > T
Cy5 = cell mean − its own ring mean (from cell_local_bg.csv).  Graphs: middle 90 % of each panel's values -> 0–1,
y axis −0.2–1.2.
"""
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage as ndi

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from cytosol import pt_engine  # noqa: E402
from cytosol.project import read_project  # noqa: E402
from cytosol.ptcore import registration  # noqa: E402

proj, lbcsv, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
EARLY = float(sys.argv[4]) if len(sys.argv) > 4 else 100.0
PCT = float(sys.argv[5]) if len(sys.argv) > 5 else 50.0
out.mkdir(parents=True, exist_ok=True)
data, files = read_project(proj)
rows, thr = [], {}
for n, _ in enumerate(data.get('images') or []):
    key = f'images/{n}/tracks.pkl'
    if key not in files:
        continue
    st = pickle.loads(files[key])
    pt = getattr(st, 'pt', None)
    if not pt:
        continue
    CID, reg, S = pt_engine._unpack(pt['arrays'])['CID'], pt['reg'], float(pt['S'])
    tcf, ref_ch = pt['sources']['reference'].rsplit('::', 1)
    mea_ch = pt['sources']['measure'].rsplit('::', 1)[1]
    name = Path(tcf).stem.split('.A1.')[-1]
    dt = float((pt.get('cfg') or {}).get('channel', {}).get('frame_interval_min', 20.0))
    A, B, _ = pt_engine.load(tcf, ref_ch, mea_ch)
    Bal = registration.align_b(B, reg)
    del A, B
    T, NF, NW = Bal.shape
    early = [z for z in range(T) if z * dt <= EARLY]
    t_img = float(np.percentile(Bal[early], PCT))
    thr[name] = t_img
    NH, NHW = CID.shape[1:]
    yy, xx = np.arange(NF), np.arange(NW)
    for z in range(T):
        hy = np.clip(np.round((yy + .5) * S - .5 + reg.dy_ht.values[z]).astype(int), 0, NH - 1)
        hx = np.clip(np.round((xx + .5) * S - .5 + reg.dx_ht.values[z]).astype(int), 0, NHW - 1)
        lab = CID[z][np.ix_(hy, hx)]
        b = Bal[z].astype(float)
        kept = np.where(b > t_img, b, 0.0)
        exc = np.clip(b - t_img, 0, None)
        pos = (b > t_img).astype(float)
        ids = np.unique(lab)
        ids = ids[ids > 0]
        if not len(ids):
            continue
        for c, a1, a2, a3 in zip(ids, ndi.mean(kept, lab, ids), ndi.mean(exc, lab, ids), ndi.mean(pos, lab, ids)):
            rows.append(dict(image=name, cell_id=int(c), frame=z + 1, green_thr=a1, green_excess=a2, green_pos_frac=a3))
    print(name, 'threshold', t_img, flush=True)
    del Bal
G = pd.DataFrame(rows)
L = pd.read_csv(lbcsv).merge(G, on=['image', 'cell_id', 'frame'], how='left')
L = L[L.long_cell].copy()
L['ratio_thr'] = np.where(L.cy5 > 0, L.green_thr / L.cy5, np.nan)
L['ratio_excess'] = np.where(L.cy5 > 0, L.green_excess / L.cy5, np.nan)
L.round(6).to_csv(out / 'cell_green_threshold.csv', index=False)
pd.Series(thr, name='threshold').to_csv(out / 'green_threshold_per_image.csv')

import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from cytosol.ptcore import plots, style  # noqa: E402
style.setup()


def band(ax, col, color, label):
    q = L.groupby('t_h')[col].quantile([.25, .5, .75]).unstack()
    ax.fill_between(q.index, q[.25], q[.75], color=color, alpha=.18)
    ax.plot(q.index, q[.5], '-', color=color, lw=2.2, label=label)


def norm(col):
    v = L[col].replace([np.inf, -np.inf], np.nan).dropna()
    lo, hi = np.percentile(v, [5, 95])
    L[f'n_{col}'] = (L[col] - lo) / (hi - lo if hi > lo else 1)
    return lo, hi


n = L.cell_uid.nunique()
panels = [('green_thr', 'tab:green', f'green (기준 이하 픽셀 = 0) 세포 평균'),
          ('green_excess', 'darkgreen', 'green − 기준 (양수만) 세포 평균'),
          ('green_pos_frac', 'tab:olive', '기준 넘는 픽셀 비율'),
          ('ratio_thr', 'tab:purple', 'green (기준 이하 = 0) / Cy5 (주변 배경 뺀 값)')]
fig, axs = plt.subplots(2, 2, figsize=(14, 9.5), sharex=True)
for a, (col, color, label) in zip(axs.flat, panels):
    lo, hi = norm(col)
    for u, g in L.groupby('cell_uid'):
        a.plot(g.t_h, g[f'n_{col}'], '-', lw=.5, alpha=.25, color=color)
    band(a, f'n_{col}', 'k', '중앙값 ± IQR')
    a.set_ylim(-0.2, 1.2)
    a.text(.01, .98, f'0 = {lo:.4g}, 1 = {hi:.4g} (전체 값의 5 · 95 백분위)', transform=a.transAxes, va='top',
           fontsize=7, color='0.35')
    a.set_title(label, fontsize=10)
    a.set_ylabel('정규화 값')
    a.grid(alpha=.3)
    a.legend(fontsize=8, loc='lower right')
for a in axs[1]:
    a.set_xlabel('시간 (h)')
t_txt = ', '.join(f'{k} {v:g}' for k, v in thr.items())
fig.suptitle(f'세포 {n}개 · green 기준 = 이미지마다 0–{EARLY:g}분 green 픽셀 {PCT:g} 백분위 ({t_txt})', fontsize=9)
plots._save(fig, str(out / 'norm_cell_green_threshold.png'))
s = L.groupby('t_h')[['green_thr', 'green_excess', 'green_pos_frac', 'ratio_thr', 'cy5']].median()
s.round(5).to_csv(out / 'cell_green_threshold_summary.csv')
print(s.round(4).iloc[::3].to_string())
