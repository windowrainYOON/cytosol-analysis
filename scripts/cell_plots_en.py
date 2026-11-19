"""English per-cell graphs (pHrodo / Cy5), legends outside the axes (owner 2026-11-19).

usage:
  python scripts/cell_plots_en.py compare DATA_CSV CELLS_CSV OUT_PNG MODE [label]
      MODE thr = cell_green_threshold.csv (pHrodo pixels <= early-time threshold set to 0)
      MODE local = local-background table (columns green, green_cell, cy5, ratio)
      chosen cells (red) and all cells (black), normalized 5 / 95 % of all cells -> 0 / 1, y −0.2–1.7
  python scripts/cell_plots_en.py thr THR_CSV OUT_PNG [percentile] [early_min]
      the 4-panel thresholded graph of all cells, y −0.2–1.2
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
kind = sys.argv[1]


def normed(L, col):
    v = L[col].replace([np.inf, -np.inf], np.nan).dropna()
    lo, hi = np.percentile(v, [5, 95])
    return (L[col] - lo) / (hi - lo if hi > lo else 1), lo, hi


def band(a, d, y, color, label, alpha_lines):
    for _, x in d.groupby('cell_uid'):
        a.plot(x.t_h, x[y], '-', lw=.5, alpha=alpha_lines, color=color)
    q = d.groupby('t_h')[y].quantile([.25, .5, .75]).unstack()
    a.fill_between(q.index, q[.25], q[.75], color=color, alpha=.18)
    return a.plot(q.index, q[.5], '-', color=color, lw=2.4, label=label)[0]


def finish(a, lo, hi, ylim):
    a.set_ylim(*ylim)
    a.text(.01, .98, f'0 = {lo:.4g}, 1 = {hi:.4g} (5th / 95th percentile of all cells)', transform=a.transAxes,
           va='top', fontsize=7, color='0.35')
    a.set_ylabel('Normalized value')
    a.grid(alpha=.3)


if kind == 'compare':
    data, cells, png, mode = sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
    lab = sys.argv[6] if len(sys.argv) > 6 else 'Selected cells'
    L = pd.read_csv(data)
    if 'long_cell' in L:
        L = L[L.long_cell].copy()
    sel = set(pd.read_csv(cells).cell)
    L['grp'] = L.cell_uid.isin(sel)
    if mode == 'thr':
        panels = [('green_thr', 'pHrodo (pixels ≤ threshold set to 0), cell mean'),
                  ('green_pos_frac', 'Fraction of pHrodo pixels above threshold'),
                  ('cy5', 'Cy5 (cell − surrounding background)'),
                  ('ratio_thr', 'pHrodo (thresholded) / Cy5')]
    else:
        panels = [('green', 'pHrodo (cell − its own surrounding background)'),
                  ('green_cell', 'pHrodo cell mean (no background subtraction)'),
                  ('cy5', 'Cy5 (cell − its own surrounding background)'),
                  ('ratio', 'pHrodo / Cy5 (each background-subtracted)')]
    fig, axs = plt.subplots(2, 2, figsize=(15, 9.5), sharex=True)
    for a, (col, ttl) in zip(axs.flat, panels):
        L['_n'], lo, hi = normed(L, col)
        h1 = band(a, L[L.grp], '_n', 'tab:red', f'{lab} (n = {L[L.grp].cell_uid.nunique()} cells), median ± IQR', .25)
        h2 = band(a, L, '_n', 'k', f'All cells (n = {L.cell_uid.nunique()}), median ± IQR', .06)
        finish(a, lo, hi, (-0.2, 1.7))
        a.set_title(ttl, fontsize=10)
    for a in axs[1]:
        a.set_xlabel('Time (h)')
    fig.legend([h1, h2], [h1.get_label(), h2.get_label()], loc='center left', bbox_to_anchor=(.86, .5), fontsize=9,
               frameon=False)
    fig.tight_layout(rect=(0, 0, .85, 1))
    plots._save(fig, png)
elif kind == 'thr':
    data, png = sys.argv[2], sys.argv[3]
    pct = sys.argv[4] if len(sys.argv) > 4 else '95'
    early = sys.argv[5] if len(sys.argv) > 5 else '100'
    L = pd.read_csv(data)
    if 'long_cell' in L:
        L = L[L.long_cell].copy()
    panels = [('green_thr', 'tab:green', 'pHrodo (pixels ≤ threshold set to 0), cell mean'),
              ('green_excess', 'darkgreen', 'pHrodo − threshold (positive part), cell mean'),
              ('green_pos_frac', 'tab:olive', 'Fraction of pHrodo pixels above threshold'),
              ('ratio_thr', 'tab:purple', 'pHrodo (thresholded) / Cy5 (background-subtracted)')]
    fig, axs = plt.subplots(2, 2, figsize=(15, 9.5), sharex=True)
    for a, (col, color, ttl) in zip(axs.flat, panels):
        L['_n'], lo, hi = normed(L, col)
        for _, x in L.groupby('cell_uid'):
            a.plot(x.t_h, x._n, '-', lw=.5, alpha=.25, color=color)
        q = L.groupby('t_h')._n.quantile([.25, .5, .75]).unstack()
        a.fill_between(q.index, q[.25], q[.75], color='k', alpha=.18)
        h = a.plot(q.index, q[.5], '-', color='k', lw=2.4, label='Median ± IQR')[0]
        finish(a, lo, hi, (-0.2, 1.2))
        a.set_title(ttl, fontsize=10)
    for a in axs[1]:
        a.set_xlabel('Time (h)')
    fig.legend([h], [f'Median ± IQR (n = {L.cell_uid.nunique()} cells); thin lines = single cells'],
               loc='center left', bbox_to_anchor=(.86, .5), fontsize=9, frameon=False)
    fig.suptitle(f'pHrodo threshold = {pct}th percentile of each image\'s pHrodo pixels in 0–{early} min', fontsize=10)
    fig.tight_layout(rect=(0, 0, .85, .97))
    plots._save(fig, png)
