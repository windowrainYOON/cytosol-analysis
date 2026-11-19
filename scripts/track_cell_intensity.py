"""Per-cell intensity over time and the particles inside cells, all images (owner question 2026-11-19).

usage: <particle-tracking>/.venv/bin/python -I scripts/track_cell_intensity.py PT_REPO COMBINED_DIR OUT
COMBINED_DIR = ParticleTracker combine output (combined_cell_intensity.csv, combined_tracks_points_A_B_HT.csv).
A = reference (Cy5), B = measure (pHrodo green). cell_* = whole cell mean minus background (ParticleTracker 세포별 밝기,
cells followed by ParticleTracker's cell IDs). Particle values = particle ROI mean minus ring background.
"""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ptracker import plots, style  # noqa: E402

style.setup()
cdir, out = Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
C = pd.read_csv(cdir / 'combined_cell_intensity.csv')
C['t_h'] = C.time_min / 60
C['cell_uid'] = C.dataset + '::' + C.cell_id.astype(str)
n = C.groupby('cell_uid').frame.transform('size')
C['long_cell'] = n >= 20
P = pd.read_csv(cdir / 'combined_tracks_points_A_B_HT.csv',
                usecols=['dataset', 'track_uid', 'frame', 'time_min', 'cell_id', 'inside_cell', 'group', 'I_A', 'I_B',
                         'I_B_max', 'ratio_BA'])
P['t_h'] = P.time_min / 60
pin = P[P.inside_cell.astype(bool) & (P.cell_id > 0)]


def band(ax, d, col, color, label):
    q = d.groupby('t_h')[col].quantile([.25, .5, .75]).unstack()
    ax.fill_between(q.index, q[.25], q[.75], color=color, alpha=.2)
    ax.plot(q.index, q[.5], '-', color=color, lw=2.2, label=label)


L = C[C.long_cell]
fig, axs = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
band(axs[0, 0], L, 'cell_I_B', 'tab:green', f'세포 전체 green (pHrodo), 세포 {L.cell_uid.nunique()}개')
axs[0, 0].set_ylabel('세포 평균 − 배경')
axs[0, 0].set_title('세포 단위 green (중앙값 ± IQR, 20프레임 이상 추적된 세포)')
band(axs[0, 1], L, 'cell_I_A', 'tab:red', 'Cy5 (reference)')
axs[0, 1].set_title('세포 단위 Cy5')
band(axs[1, 0], pin, 'I_B', 'tab:green', 'green (배경 제거)')
band(axs[1, 0], pin, 'I_B_max', 'darkgreen', 'green ROI 최댓값 (raw)')
axs[1, 0].set_title(f'세포 안 입자 (모든 시점, {len(pin):,}점)')
per = pin.groupby(['dataset', 'cell_id', 'frame', 't_h']).agg(n=('I_B', 'size'), sumB=('I_B', 'sum'),
                                                            green=('I_B_max', lambda v: (v >= 5).sum())).reset_index()
band(axs[1, 1], per, 'n', 'tab:blue', '세포당 입자 수')
band(axs[1, 1], per, 'green', 'tab:green', '세포당 green ≥ 5 입자 수')
axs[1, 1].set_title('세포당 입자 수 / green 입자 수')
for a in axs.flat:
    a.grid(alpha=.3)
    a.legend(fontsize=8)
for a in axs[1]:
    a.set_xlabel('시간 (h)')
plots._save(fig, str(out / 'cell_intensity_overview.png'))

# per-cell spaghetti of green, coloured by image
fig, ax = plt.subplots(figsize=(11, 5.5))
for i, (u, g) in enumerate(L.groupby('cell_uid')):
    ax.plot(g.t_h, g.cell_I_B, '-', lw=.8, alpha=.6, color=plots.DS_COLORS(sorted(C.dataset.unique()).index(g.dataset.iloc[0]) % 10))
band(ax, L, 'cell_I_B', 'k', '중앙값 ± IQR')
ax.set_xlabel('시간 (h)')
ax.set_ylabel('세포 green (평균 − 배경)')
ax.set_title('세포별 green 시간 곡선 (색 = 이미지)')
ax.grid(alpha=.3)
ax.legend()
plots._save(fig, str(out / 'cell_green_per_cell.png'))

# raw, background and raw − background per cell (owner 2026-11-19: why does cell green fall late?)
fig, axs = plt.subplots(1, 2, figsize=(14, 5))
for a, ch, name in ((axs[0], 'B', 'green (pHrodo)'), (axs[1], 'A', 'Cy5 (reference)')):
    band(a, L, f'cell_I_{ch}_raw', 'tab:blue', '세포 평균 (배경 빼기 전)')
    band(a, L, f'cell_bg_{ch}', 'tab:orange', '세포 주변 배경')
    band(a, L, f'cell_I_{ch}', 'k', '세포 − 배경')
    a.set_title(f'세포 단위 {name} (세포 {L.cell_uid.nunique()}개, 중앙값 ± IQR)')
    a.set_xlabel('시간 (h)')
    a.set_ylabel('형광 (raw)')
    a.grid(alpha=.3)
    a.legend(fontsize=8)
plots._save(fig, str(out / 'cell_raw_background_subtracted.png'))
L.groupby('t_h').agg(green_raw=('cell_I_B_raw', 'median'), green_bg=('cell_bg_B', 'median'),
                     green=('cell_I_B', 'median'), green_raw_mean=('cell_I_B_raw', 'mean'),
                     green_bg_mean=('cell_bg_B', 'mean'), green_mean=('cell_I_B', 'mean'),
                     cy5_raw=('cell_I_A_raw', 'median'), cy5_bg=('cell_bg_A', 'median'), cy5=('cell_I_A', 'median')) \
    .round(4).to_csv(out / 'cell_raw_background_summary.csv')

# green background stable window (owner 2026-11-19: cut the start / end where the green background jumps)
BG_FRAC = 0.2
fr = L.groupby('t_h').cell_bg_B.apply(lambda v: (v >= 1).mean())
ok = (fr <= BG_FRAC).to_numpy()
best, cur, start = (0, 0), 0, 0
for i, o in enumerate(ok):
    if o:
        if cur == 0:
            start = i
        cur += 1
        if cur > best[1] - best[0]:
            best = (start, i + 1)
    else:
        cur = 0
t0, t1 = fr.index[best[0]], fr.index[best[1] - 1]
(out / 'green_stable_window.txt').write_text(
    f'green background stable: {t0:.2f}–{t1:.2f} h (longest run of frames where <= {BG_FRAC:.0%} of the cells '
    f'have a green ring background >= 1)\n' + fr.round(3).to_string() + '\n', encoding='utf-8')
W = L[L.t_h.between(t0, t1)]
Pw = pin[pin.t_h.between(t0, t1)]
perw = per[per.t_h.between(t0, t1)]
fig, axs = plt.subplots(2, 2, figsize=(14, 9), sharex=True)
for a, ch, name in ((axs[0, 0], 'B', 'green (pHrodo)'), (axs[0, 1], 'A', 'Cy5 (reference)')):
    band(a, W, f'cell_I_{ch}_raw', 'tab:blue', '세포 평균 (배경 빼기 전)')
    band(a, W, f'cell_bg_{ch}', 'tab:orange', '세포 주변 배경')
    band(a, W, f'cell_I_{ch}', 'k', '세포 − 배경')
    a.set_title(f'세포 단위 {name} (세포 {W.cell_uid.nunique()}개)')
    a.set_ylabel('형광 (raw)')
band(axs[1, 0], Pw, 'I_B', 'tab:green', 'green (배경 제거)')
axs[1, 0].set_title('세포 안 입자 green')
band(axs[1, 1], perw, 'n', 'tab:blue', '세포당 입자 수')
band(axs[1, 1], perw, 'green', 'tab:green', '세포당 green ≥ 5 입자 수')
axs[1, 1].set_title('세포당 입자 수 / green 입자 수')
for a in axs.flat:
    a.grid(alpha=.3)
    a.legend(fontsize=8)
for a in axs[1]:
    a.set_xlabel('시간 (h)')
fig.suptitle(f'green 배경이 안정적인 구간만: {t0:.1f}–{t1:.1f} h (중앙값 ± IQR)')
plots._save(fig, str(out / 'cell_intensity_green_stable_window.png'))
print(f'green stable window {t0:.2f}-{t1:.2f} h')

C.round(5).to_csv(out / 'cell_intensity_all.csv', index=False)
per.round(4).to_csv(out / 'cell_particle_counts_per_frame.csv', index=False)
s = L.groupby('t_h').agg(cells=('cell_uid', 'nunique'), green_median=('cell_I_B', 'median'),
                         cy5_median=('cell_I_A', 'median'), ratio_median=('cell_ratio_BA', 'median'))
pp = per.groupby('t_h').agg(particles_per_cell=('n', 'median'), green_particles_per_cell=('green', 'mean'))
s.join(pp).round(4).to_csv(out / 'cell_timecourse_summary.csv')
print(s.join(pp).round(3).iloc[[0, 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 34]].to_string())
print('cells', C.cell_uid.nunique(), 'long cells', L.cell_uid.nunique())
