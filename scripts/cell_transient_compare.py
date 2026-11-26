"""Transient (rise-then-fall) cells of two experiments and a comparison figure (owner 2026-11-26).

usage: python scripts/cell_transient_compare.py OUT NAME_A LOCAL_BG_A.csv NAME_B LOCAL_BG_B.csv

Per cell, from cell_local_bg.csv (pHrodo = cell mean − its own 2–6 µm ring mean; Cy5 likewise), the pHrodo curve is
smoothed with a 3-frame running median and (the 2026-11-19 261118 rule, reproduces its 11 cells):
  base = median 1–1.7 h, peak = max 2–6 h (t_peak), late = median 7–9.5 h
  amp = peak − base, fall = (peak − late) / amp
  transient = amp in the top 25 % of that experiment's long cells and fall >= 0.6
Also 'transient_A_scale': amp / (P95 − P5 of all that experiment's pHrodo values) >= the same normalised cut-off as
experiment A's top-25 % value, so both experiments are judged on one relative scale.
Outputs in OUT: transient_cells_<name>.csv, cell_rise_fall_<name>.csv, transient_summary.csv, en_transient_compare.png
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

from cytosol.ptcore import style  # noqa: E402

style.setup()
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
exps = [(sys.argv[2], pd.read_csv(sys.argv[3])), (sys.argv[4], pd.read_csv(sys.argv[5]))]
COL = {exps[0][0]: '#1f4e9c', exps[1][0]: '#c0392b'}


def rise_fall(C):
    L = C[C.long_cell].sort_values(['cell_uid', 'frame']).copy()
    L['gs'] = L.groupby('cell_uid').green.transform(lambda v: v.rolling(3, center=True, min_periods=1).median())
    rows = []
    for u, g in L.groupby('cell_uid'):
        w = g[(g.t_h >= 2) & (g.t_h <= 6)]
        if w.empty:
            continue
        base = g[(g.t_h >= 1) & (g.t_h <= 1.7)].gs.median()
        late = g[(g.t_h >= 7) & (g.t_h <= 9.5)].gs.median()
        i = w.gs.idxmax()
        pk = float(w.gs.max())
        amp = pk - base
        rows.append(dict(cell=u, base=base, peak=pk, t_peak=float(w.t_h[i]), late=late, amp=amp,
                         fall=(pk - late) / amp if amp > 0 else np.nan,
                         cy5_peak=float(g[(g.t_h >= 2) & (g.t_h <= 6)].cy5.max()),
                         area=float(g.cell_area_flpx.median()), n_frames=len(g)))
    return L, pd.DataFrame(rows)


res = {}
for name, C in exps:
    L, R = rise_fall(C)
    span = np.nanpercentile(L.green, 95) - np.nanpercentile(L.green, 5)
    R['amp_norm'] = R.amp / span
    R['transient'] = (R.amp >= R.amp.quantile(.75)) & (R.fall >= .6)
    res[name] = dict(L=L, R=R, span=span, lo=np.nanpercentile(L.green, 5))
cut = res[exps[0][0]]['R'].amp_norm.quantile(.75)
summ = []
for name, d in res.items():
    R = d['R']
    R['transient_A_scale'] = (R.amp_norm >= cut) & (R.fall >= .6)
    R.round(5).sort_values('amp', ascending=False).to_csv(out / f'cell_rise_fall_{name}.csv', index=False)
    R[R.transient].round(5).sort_values('amp', ascending=False).to_csv(out / f'transient_cells_{name}.csv',
                                                                       index=False)
    T = R[R.transient]
    summ.append(dict(experiment=name, long_cells=len(R), transient=int(R.transient.sum()),
                     transient_frac=R.transient.mean(), transient_A_scale=int(R.transient_A_scale.sum()),
                     amp_cutoff_top25=R.amp.quantile(.75), amp_norm_cutoff_A=cut, pHrodo_span_P5_P95=d['span'],
                     all_amp_median=R.amp.median(), all_amp_norm_median=R.amp_norm.median(),
                     all_fall_median=R.fall.median(),
                     tr_amp_median=T.amp.median(), tr_amp_norm_median=T.amp_norm.median(),
                     tr_fall_median=T.fall.median(), tr_t_peak_median=T.t_peak.median(),
                     tr_cy5_peak_median=T.cy5_peak.median(), other_cy5_peak_median=R[~R.transient].cy5_peak.median()))
S = pd.DataFrame(summ)
S.round(5).to_csv(out / 'transient_summary.csv', index=False)
print(S.round(4).T.to_string())


def band(ax, L, col, label, key='n', ls='-'):
    g = L.groupby(L.t_h.round(3))[key]
    m, q1, q3 = g.median(), g.quantile(.25), g.quantile(.75)
    ax.fill_between(m.index, q1, q3, color=col, alpha=.15, lw=0)
    ax.plot(m.index, m, color=col, ls=ls, lw=1.8, label=label)


fig, axs = plt.subplots(2, 3, figsize=(15, 8.4))
for name, d in res.items():
    L, R = d['L'], d['R']
    L['n'] = (L.gs - d['lo']) / d['span']
    c5 = L.cy5
    L['c'] = (c5 - np.nanpercentile(c5, 5)) / (np.nanpercentile(c5, 95) - np.nanpercentile(c5, 5))
    tr = set(R.cell[R.transient])
    col = COL[name]
    band(axs[0, 0], L, col, f'{name} all cells (n={len(R)})')
    band(axs[0, 1], L[L.cell_uid.isin(tr)], col, f'{name} transient (n={len(tr)})')
    band(axs[0, 2], L[L.cell_uid.isin(tr)], col, f'{name} transient', key='c')
    band(axs[0, 2], L[~L.cell_uid.isin(tr)], col, f'{name} other', key='c', ls='--')
    top = tr or set(R.cell[R.amp >= R.amp.quantile(.75)])   # no transient cell: the top-25 % risers instead
    for j, u in enumerate(top):
        g = L[L.cell_uid == u]
        axs[1, 0].plot(g.t_h, g.n, color=col, lw=.8, alpha=.6,
                       label=(f'{name} transient (n={len(top)})' if tr else f'{name} top-25 % rise (n={len(top)})')
                       if j == 0 else None)
    axs[1, 1].scatter(R.amp_norm[~R.transient], R.fall[~R.transient], s=18, facecolors='none', edgecolors=col,
                      label=f'{name} other')
    axs[1, 1].scatter(R.amp_norm[R.transient], R.fall[R.transient], s=26, color=col, label=f'{name} transient')
x = np.arange(len(S))
axs[1, 2].bar(x, S.transient_frac * 100, color=[COL[n] for n in S.experiment])
for i, r in S.iterrows():
    axs[1, 2].text(i, r.transient_frac * 100 + .5, f'{r.transient}/{r.long_cells}', ha='center')
axs[1, 2].set_xticks(x, S.experiment)
axs[1, 2].set_ylabel('transient cells (%)')
axs[1, 2].set_title('Fraction of transient cells')
axs[1, 2].set_ylim(0, max(S.transient_frac.max() * 100 * 1.25, 5))
axs[1, 1].axhline(.6, color='k', lw=.8, ls=':')
axs[1, 1].axvline(cut, color='k', lw=.8, ls=':')
axs[1, 1].set_xlabel('rise (peak 2–6 h − base 1–1.7 h), normalized')
axs[1, 1].set_ylabel('fall fraction (peak − 7–9.5 h) / rise')
axs[1, 1].set_title('Rise vs fall per cell')
axs[1, 1].set_ylim(-1.5, 2.5)
axs[1, 0].set_title('Each cell: transient (or largest rises)')
for ax, t in [(axs[0, 0], 'pHrodo, all cells'), (axs[0, 1], 'pHrodo, transient cells')]:
    ax.set_title(t)
axs[0, 2].set_title('Cy5, transient vs other cells')
for ax in (axs[0, 0], axs[0, 1], axs[0, 2], axs[1, 0]):
    ax.set_xlabel('time (h)')
    ax.set_ylim(-.2, 1.7)
    ax.axvspan(2, 6, color='0.9', zorder=0)
    ax.set_ylabel('normalized (P5–P95 of each experiment → 0–1)')
for ax in (axs[0, 0], axs[0, 1], axs[0, 2], axs[1, 0], axs[1, 1]):
    ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1), frameon=False, fontsize=8)
fig.suptitle('Rise-then-fall cells: pHrodo (cell − own 2–6 µm ring), 3-frame median', y=1.0)
fig.tight_layout()
fig.savefig(out / 'en_transient_compare.png', dpi=200, bbox_inches='tight')
print('saved', out / 'en_transient_compare.png')
