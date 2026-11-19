"""Graphs of cell_local_bg.csv (per-cell green / Cy5 with each cell's own local ring background).

usage: python scripts/cell_local_bg_plots.py CSV OUT
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
C = pd.read_csv(sys.argv[1])
out = Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
L = C[C.long_cell].copy()
n = L.cell_uid.nunique()


def band(ax, d, col, color, label, ls='-'):
    q = d.groupby('t_h')[col].quantile([.25, .5, .75]).unstack()
    ax.fill_between(q.index, q[.25], q[.75], color=color, alpha=.18)
    ax.plot(q.index, q[.5], ls, color=color, lw=2.2, label=label)


# baseline of each cell: median of its first 3 frames from 1 h on (green background settled)
def base(g, col):
    b = g[g.t_h >= 1].sort_values('t_h')[col].head(3)
    return b.median() if len(b) else np.nan


for col in ('green', 'cy5', 'green_cell', 'cy5_cell'):
    L[f'd_{col}'] = L[col] - L.groupby('cell_uid')[col].transform(lambda s, c=col: base(L.loc[s.index], c))
L['cy5_rel'] = L.cy5 / L.groupby('cell_uid').cy5.transform(lambda s: base(L.loc[s.index], 'cy5'))

# 1. green / Cy5 per cell
fig, axs = plt.subplots(1, 2, figsize=(14, 5))
band(axs[0], L, 'ratio_raw', 'tab:purple', 'green / Cy5 (세포 평균, 배경 빼기 전)')
axs[0].set_title(f'세포 단위 green / Cy5 (배경 빼기 전, 세포 {n}개)')
band(axs[1], L, 'ratio', 'tab:purple', 'green / Cy5 (각자 주변 배경 뺀 뒤)')
axs[1].axhline(0, color='k', lw=.6)
axs[1].set_title('세포 단위 green / Cy5 (세포마다 주변 고리 평균을 뺀 값)')
for a in axs:
    a.set_xlabel('시간 (h)')
    a.set_ylabel('green / Cy5')
    a.grid(alpha=.3)
    a.legend(fontsize=8)
plots._save(fig, str(out / 'cell_green_over_cy5.png'))

# 2. the background shift: cell vs its own ring
fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for a, ch, name in ((axs[0], 'green', 'green (pHrodo)'), (axs[1], 'cy5', 'Cy5')):
    band(a, L, f'{ch}_cell', 'tab:blue', '세포 평균')
    band(a, L, f'{ch}_ring', 'tab:orange', '그 세포의 주변 고리 평균 (2–6 µm)')
    band(a, L, ch, 'k', '세포 − 주변 고리')
    a.set_title(f'세포 단위 {name}: 세포와 그 세포 주변 배경 (세포 {n}개)')
    a.set_xlabel('시간 (h)')
    a.set_ylabel('형광 (raw)')
    a.grid(alpha=.3)
    a.legend(fontsize=8)
plots._save(fig, str(out / 'cell_vs_own_background.png'))

# 3. change of each cell from its own baseline, background shift taken out per cell
fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for u, g in L.groupby('cell_uid'):
    axs[0].plot(g.t_h, g.d_green, '-', lw=.6, alpha=.35, color='tab:green')
band(axs[0], L, 'd_green', 'k', '중앙값 ± IQR')
band(axs[0], L, 'd_green_cell', 'tab:blue', '참고: 배경 빼기 전 변화', ls='--')
axs[0].axhline(0, color='k', lw=.6)
axs[0].set_title('세포별 green 증감 (자기 주변 배경 이동을 뺀 뒤, 1 h 기준)')
axs[0].set_ylabel('Δ green (세포 − 주변) − 기준값')
for u, g in L.groupby('cell_uid'):
    axs[1].plot(g.t_h, g.cy5_rel, '-', lw=.6, alpha=.35, color='tab:red')
band(axs[1], L, 'cy5_rel', 'k', '중앙값 ± IQR')
axs[1].axhline(1, color='k', lw=.6)
axs[1].set_title('세포별 Cy5 증감 (자기 주변 배경 뺀 뒤, 1 h 기준 배수)')
axs[1].set_ylabel('Cy5 / 1 h 값')
for a in axs:
    a.set_xlabel('시간 (h)')
    a.grid(alpha=.3)
    a.legend(fontsize=8)
plots._save(fig, str(out / 'cell_change_local_bg.png'))

s = L.groupby('t_h').agg(cells=('cell_uid', 'nunique'), green_cell=('green_cell', 'median'),
                         green_ring=('green_ring', 'median'), green=('green', 'median'), d_green=('d_green', 'median'),
                         cy5_cell=('cy5_cell', 'median'), cy5_ring=('cy5_ring', 'median'), cy5=('cy5', 'median'),
                         cy5_rel=('cy5_rel', 'median'), ratio_raw=('ratio_raw', 'median'), ratio=('ratio', 'median'))
s.round(4).to_csv(out / 'cell_local_bg_summary.csv')
L.round(5).to_csv(out / 'cell_local_bg_long_cells.csv', index=False)
print(s.round(3).iloc[::3].to_string())


# ---- normalized versions (owner 2026-11-19): the middle 90 % of all values of a panel -> 0–1, y axis 0–1 --------
def norm(cols):
    v = pd.concat([L[c] for c in cols]).replace([np.inf, -np.inf], np.nan).dropna()
    lo, hi = np.percentile(v, [5, 95])
    for c in cols:
        L[f'n_{c}'] = (L[c] - lo) / (hi - lo if hi > lo else 1)
    return lo, hi


def ylim01(a, lo, hi, unit=''):
    a.set_ylim(-0.2, 1.2)
    a.text(.01, .98, f'0 = {lo:.4g}, 1 = {hi:.4g}{unit} (전체 값의 5 · 95 백분위)', transform=a.transAxes, va='top',
           fontsize=7, color='0.35')


fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for a, col, ttl in ((axs[0], 'ratio_raw', '배경 빼기 전'), (axs[1], 'ratio', '각자 주변 배경 뺀 뒤')):
    lo, hi = norm([col])
    band(a, L, f'n_{col}', 'tab:purple', 'green / Cy5 (정규화)')
    ylim01(a, lo, hi)
    a.set_title(f'세포 단위 green / Cy5 ({ttl}, 세포 {n}개)')
    a.set_xlabel('시간 (h)')
    a.set_ylabel('정규화 값')
    a.grid(alpha=.3)
    a.legend(fontsize=8, loc='lower right')
plots._save(fig, str(out / 'norm_cell_green_over_cy5.png'))

fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for a, ch, name in ((axs[0], 'green', 'green (pHrodo)'), (axs[1], 'cy5', 'Cy5')):
    lo, hi = norm([f'{ch}_cell', f'{ch}_ring', ch])
    band(a, L, f'n_{ch}_cell', 'tab:blue', '세포 평균')
    band(a, L, f'n_{ch}_ring', 'tab:orange', '그 세포의 주변 고리 평균')
    band(a, L, f'n_{ch}', 'k', '세포 − 주변 고리')
    ylim01(a, lo, hi)
    a.set_title(f'세포 단위 {name}: 세포와 그 세포 주변 배경 (정규화)')
    a.set_xlabel('시간 (h)')
    a.set_ylabel('정규화 값')
    a.grid(alpha=.3)
    a.legend(fontsize=8, loc='lower right')
plots._save(fig, str(out / 'norm_cell_vs_own_background.png'))

fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for a, col, color, ttl in ((axs[0], 'd_green', 'tab:green', '세포별 green 증감 (주변 배경 뺀 뒤, 1 h 기준)'),
                           (axs[1], 'cy5_rel', 'tab:red', '세포별 Cy5 증감 (주변 배경 뺀 뒤, 1 h 기준 배수)')):
    lo, hi = norm([col])
    for u, g in L.groupby('cell_uid'):
        a.plot(g.t_h, g[f'n_{col}'], '-', lw=.6, alpha=.35, color=color)
    band(a, L, f'n_{col}', 'k', '중앙값 ± IQR')
    ylim01(a, lo, hi)
    a.set_title(ttl)
    a.set_xlabel('시간 (h)')
    a.set_ylabel('정규화 값')
    a.grid(alpha=.3)
    a.legend(fontsize=8, loc='lower right')
plots._save(fig, str(out / 'norm_cell_change_local_bg.png'))
