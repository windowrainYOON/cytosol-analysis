"""ParticleTracker-style comparison plots: long tracks with green (CH0 >= thr in >= n frames) vs without.

usage: python scripts/track_green_plots.py REPO PT_FOLDER OUT_DIR [thr] [min_green] [min_len]"""
import sys
from pathlib import Path

repo, pt, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
thr = float(sys.argv[4]) if len(sys.argv) > 4 else 5
min_green = int(sys.argv[5]) if len(sys.argv) > 5 else 3
min_len = int(sys.argv[6]) if len(sys.argv) > 6 else 10
sys.path.insert(0, str(repo))
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from cytosol.ptcore import plots, style  # noqa: E402

style.setup()
out.mkdir(parents=True, exist_ok=True)
p = pd.read_csv(pt / 'tracks_points_A_B_HT.csv')
s = pd.read_csv(pt / 'tracks_summary_A_B_HT.csv')
ids = s.loc[s.n_points >= min_len, 'track_id']
d = p[p.track_id.isin(ids)].copy()
ng = (d.I_B_max >= thr).groupby(d.track_id).sum()
green = set(ng[ng >= min_green].index)
d['group'] = ['inside' if t in green else 'outside' for t in d.track_id]
NAMES = {'inside': f'green 있음 (CH0 ≥ {thr:g}, {min_green}프레임 이상)', 'outside': 'green 없음'}
plots.GNAME.update({'inside': 'green 있음', 'outside': 'green 없음'})

# ratio, as ParticleTracker's figure (same code), then renamed
tmp = out / '_tmp'
tmp.mkdir(exist_ok=True)
plots.ratio_figures(d, str(tmp))
for f, new in [('ratio_inside_vs_outside.png', 'ratio_green_vs_nongreen.png'),
               ('ratio_timecourse_inside.png', 'ratio_timecourse_green.png'),
               ('ratio_timecourse_outside.png', 'ratio_timecourse_nongreen.png')]:
    if (tmp / f).exists():
        (tmp / f).replace(out / new)
import shutil; shutil.rmtree(tmp, ignore_errors=True)

# the same comparison for green intensity itself
d['t_h'] = d.time_min / 60
for var, ylab, fn in [('I_B_raw', 'I(measure) CH0 평균 (raw)', 'green_mean_green_vs_nongreen.png'),
                      ('I_B_max', 'I(measure) CH0 최댓값 (raw)', 'green_max_green_vs_nongreen.png')]:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for g, c in [('inside', 'tab:green'), ('outside', 'tab:gray')]:
        q = d[d.group == g].groupby('t_h')[var].quantile([.25, .5, .75]).unstack()
        if len(q):
            ax.fill_between(q.index, q[.25], q[.75], color=c, alpha=.2)
            ax.plot(q.index, q[.5], '-', color=c, lw=2.5,
                    label=f"{NAMES[g]} (n={d[d.group == g].track_id.nunique()}, 중앙값 ± IQR)")
    if var == 'I_B_max':
        ax.axhline(thr, color='k', ls='--', lw=1, label=f'LUT 최솟값 {thr:g}')
    ax.set_xlabel('시간 (h)')
    ax.set_ylabel(ylab)
    ax.set_title(f'{ylab}: green 있음 vs green 없음 (긴 트랙 ≥ {min_len}프레임)')
    ax.grid(alpha=.3)
    ax.legend()
    plots._save(fig, str(out / fn))

# ratio with the long-track legend text spelled out (same as ParticleTracker but group names explicit)
fig, ax = plt.subplots(figsize=(10, 5.5))
for g, c in [('inside', 'tab:green'), ('outside', 'tab:gray')]:
    q = d[d.group == g].groupby('t_h').ratio_BA.quantile([.25, .5, .75]).unstack()
    if len(q):
        ax.fill_between(q.index, q[.25], q[.75], color=c, alpha=.2)
        ax.plot(q.index, q[.5], '-', color=c, lw=2.5,
                label=f"{NAMES[g]} (n={d[d.group == g].track_id.nunique()}, 중앙값 ± IQR)")
ax.set_xlabel('시간 (h)')
ax.set_ylabel('I(measure)/I(reference)')
ax.set_title('I(measure)/I(reference): green 있음 vs green 없음')
ax.grid(alpha=.3)
ax.legend()
plots._save(fig, str(out / 'ratio_green_vs_nongreen.png'))
print('green', len(green), 'non-green', d.track_id.nunique() - len(green))
