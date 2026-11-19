"""Same normalized per-cell graphs for a chosen set of cells vs the rest.

usage: python scripts/cell_group_compare.py THR_CSV CELLS_CSV OUT_PNG [label]
THR_CSV = cell_green_threshold.csv (cell_green_thr.py), CELLS_CSV has a 'cell' column (image::cell_id).
Normalization: 5 / 95 percentiles of all cells' values of the panel -> 0 / 1 (same scale for both groups), y −0.2–1.2.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from cytosol.ptcore import plots, style  # noqa: E402

style.setup()
L = pd.read_csv(sys.argv[1])
sel = set(pd.read_csv(sys.argv[2]).cell)
lab = sys.argv[4] if len(sys.argv) > 4 else '선택 세포'
L['grp'] = L.cell_uid.isin(sel)
L['cy5_d'] = L.cy5
panels = [('green_thr', 'green (기준 이하 = 0) 세포 평균'), ('green_pos_frac', '기준 넘는 픽셀 비율'),
          ('cy5_d', 'Cy5 (세포 − 주변)'), ('ratio_thr', 'green (기준 이하 = 0) / Cy5')]
fig, axs = plt.subplots(2, 2, figsize=(14, 9.5), sharex=True)
for a, (col, ttl) in zip(axs.flat, panels):
    v = L[col].replace([np.inf, -np.inf], np.nan).dropna()
    lo, hi = np.percentile(v, [5, 95])
    L['_n'] = (L[col] - lo) / (hi - lo if hi > lo else 1)
    for g, color, name in ((True, 'tab:red', f'{lab} ({L[L.grp].cell_uid.nunique()}개)'),
                           (False, '0.4', f'나머지 ({L[~L.grp].cell_uid.nunique()}개)')):
        d = L[L.grp == g]
        for u, x in d.groupby('cell_uid'):
            a.plot(x.t_h, x._n, '-', lw=.5, alpha=.25 if g else .12, color=color)
        q = d.groupby('t_h')._n.quantile([.25, .5, .75]).unstack()
        a.fill_between(q.index, q[.25], q[.75], color=color, alpha=.18)
        a.plot(q.index, q[.5], '-', color=color, lw=2.4, label=f'{name} 중앙값 ± IQR')
    a.set_ylim(-0.2, 1.2)
    a.text(.01, .98, f'0 = {lo:.4g}, 1 = {hi:.4g} (전체 세포 값의 5 · 95 백분위)', transform=a.transAxes, va='top',
           fontsize=7, color='0.35')
    a.set_title(ttl, fontsize=10)
    a.set_ylabel('정규화 값')
    a.grid(alpha=.3)
    a.legend(fontsize=8, loc='upper left', bbox_to_anchor=(0, .93))
for a in axs[1]:
    a.set_xlabel('시간 (h)')
plots._save(fig, sys.argv[3])
print(L.groupby(['grp', 't_h'])[['green_thr', 'cy5_d']].median().unstack(0).iloc[::3].round(4).to_string())
