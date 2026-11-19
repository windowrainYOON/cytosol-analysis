"""Whole-dataset (all images) graphs from the per-image ParticleTracker tables.

usage: python scripts/track_integrate.py REPO ROOT OUT [thr] [min_green] [min_len]
ROOT holds <image>_<ID>/<image>_ParticleTracker/ folders."""
import sys
from pathlib import Path

repo, root, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
thr = float(sys.argv[4]) if len(sys.argv) > 4 else 5
min_green = int(sys.argv[5]) if len(sys.argv) > 5 else 3
min_len = int(sys.argv[6]) if len(sys.argv) > 6 else 10
sys.path.insert(0, str(repo))
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from cytosol.ptcore import plots, style  # noqa: E402

style.setup()
out.mkdir(parents=True, exist_ok=True)
P, S = [], []
for k, pt in enumerate([q for q in sorted(root.glob('*_*/*_ParticleTracker'))
                        if not q.name.startswith('._') and not q.parent.name.startswith('._')], 1):
    if not (pt / 'tracks_summary_A_B_HT.csv').exists():
        continue
    img = pt.parent.name.split('.A1.')[-1].split('_')[0]
    p = pd.read_csv(pt / 'tracks_points_A_B_HT.csv')
    s = pd.read_csv(pt / 'tracks_summary_A_B_HT.csv')
    for d in (p, s):
        d.insert(0, 'dataset', img)
        d.insert(1, 'track_id_image', d['track_id'])
        d['track_id'] = d['track_id'] + k * 100000
    P.append(p)
    S.append(s)
p, s = pd.concat(P, ignore_index=True), pd.concat(S, ignore_index=True)
p.to_csv(out / 'all_tracks_points_A_B_HT.csv', index=False)
s.to_csv(out / 'all_tracks_summary_A_B_HT.csv', index=False)

# 1. ParticleTracker's own figures over all images (inside / outside, long tracks)
plots.GNAME.update({'inside': '세포 안', 'outside': '세포 밖'})
plots.ratio_figures(p, str(out), prefix='all_')
plots.per_dataset_medians(p, str(out / 'all_per_image_medians_inside_outside.png'))

# 2. green vs non-green over all images (long tracks, no inside / outside split)
long_ids = s.loc[s.n_points >= min_len, 'track_id']
d = p[p.track_id.isin(long_ids)].copy()
ng = (d.I_B_max >= thr).groupby(d.track_id).sum()
green = set(ng[ng >= min_green].index)
d['green'] = d.track_id.isin(green)
d['t_h'] = d.time_min / 60
lab = {True: f'green 있음 (CH0 ≥ {thr:g}, {min_green}프레임 이상)', False: 'green 없음'}
for var, ylab, fn in [('ratio_BA', 'I(measure)/I(reference)', 'all_ratio_green_vs_nongreen.png'),
                      ('I_B_raw', 'I(measure) CH0 평균 (raw)', 'all_green_mean_green_vs_nongreen.png'),
                      ('I_B_max', 'I(measure) CH0 최댓값 (raw)', 'all_green_max_green_vs_nongreen.png')]:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    for g, c in [(True, 'tab:green'), (False, 'tab:gray')]:
        q = d[d.green == g].groupby('t_h')[var].quantile([.25, .5, .75]).unstack()
        if len(q):
            ax.fill_between(q.index, q[.25], q[.75], color=c, alpha=.2)
            ax.plot(q.index, q[.5], '-', color=c, lw=2.5,
                    label=f'{lab[g]} (n={d[d.green == g].track_id.nunique()}, 이미지 {d.dataset.nunique()}개, 중앙값 ± IQR)')
    if var == 'I_B_max':
        ax.axhline(thr, color='k', ls='--', lw=1, label=f'LUT 최솟값 {thr:g}')
    ax.set_xlabel('시간 (h)')
    ax.set_ylabel(ylab)
    ax.set_title(f'{ylab}: green 있음 vs green 없음 (전체 이미지, 긴 트랙 ≥ {min_len}프레임)')
    ax.grid(alpha=.3)
    ax.legend()
    plots._save(fig, str(out / fn))

# per-image medians, green vs non-green
fig, ax = plt.subplots(figsize=(11, 6))
for i, ds in enumerate(sorted(d.dataset.unique())):
    for g, ls in [(True, '-'), (False, '--')]:
        m = d[(d.dataset == ds) & (d.green == g)].groupby('t_h').ratio_BA.median()
        if len(m):
            ax.plot(m.index, m.values, ls, color=plots.DS_COLORS(i), lw=1.5, label=f'{ds} {"green" if g else "non-green"}')
ax.set_xlabel('시간 (h)')
ax.set_ylabel('I(measure)/I(reference) 중앙값')
ax.set_title('이미지별 중앙값 (실선 = green 있음, 점선 = green 없음)')
ax.grid(alpha=.3)
ax.legend(ncol=4, fontsize=7)
plots._save(fig, str(out / 'all_per_image_medians_green.png'))

# fraction of long tracks that turn green, and when
rows = []
for ds, g in d.groupby('dataset'):
    ids = g.track_id.unique()
    gi = [t for t in ids if t in green]
    first = g[g.green & (g.I_B_max >= thr)].groupby('track_id').time_min.min() / 60
    rows.append(dict(image=ds, tracks_all=int((s.dataset == ds).sum()), long_tracks=len(ids),
                     inside=int(((s.dataset == ds) & (s.group == 'inside')).sum()),
                     outside=int(((s.dataset == ds) & (s.group == 'outside')).sum()),
                     green_tracks=len(gi), green_fraction=round(len(gi) / max(len(ids), 1), 4),
                     green_first_h_median=round(float(first.median()), 2) if len(first) else np.nan))
summ = pd.DataFrame(rows)
tot = dict(image='전체', tracks_all=summ.tracks_all.sum(), long_tracks=summ.long_tracks.sum(),
           inside=summ.inside.sum(), outside=summ.outside.sum(), green_tracks=summ.green_tracks.sum())
tot['green_fraction'] = round(tot['green_tracks'] / tot['long_tracks'], 4)
summ = pd.concat([summ, pd.DataFrame([tot])], ignore_index=True)
summ.to_csv(out / 'per_image_summary.csv', index=False)
fig, ax = plt.subplots(figsize=(10, 4.5))
b = summ[summ.image != '전체']
ax.bar(b.image, b.green_fraction * 100, color='tab:green')
for x, (n, f) in enumerate(zip(b.green_tracks, b.green_fraction)):
    ax.text(x, f * 100, str(n), ha='center', va='bottom', fontsize=8)
ax.set_ylabel('green 트랙 / 긴 트랙 (%)')
ax.set_title(f'이미지별 green 트랙 비율 (막대 위 숫자 = 트랙 수, 전체 {tot["green_fraction"] * 100:.1f} %)')
ax.grid(alpha=.3, axis='y')
plots._save(fig, str(out / 'per_image_green_fraction.png'))
pd.Series(sorted(green)).rename('track_id').to_csv(out / 'all_green_track_ids.csv', index=False)
print(summ.to_string(index=False))
