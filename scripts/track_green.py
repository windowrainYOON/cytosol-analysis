"""Long tracks with green (measure, CH0) signal above a LUT threshold, no inside/outside split.

usage: python scripts/track_green.py PT_FOLDER OUT_DIR [--thr 5] [--min-len 10] [--min-green 3]
A frame is green when the particle ROI's brightest CH0 pixel (I_B_max) >= thr,
i.e. the particle is visible with the green LUT minimum at thr."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('pt', type=Path)
ap.add_argument('out', type=Path)
ap.add_argument('--thr', type=float, default=5)
ap.add_argument('--min-len', type=int, default=10)
ap.add_argument('--min-green', type=int, default=3)
a = ap.parse_args()
a.out.mkdir(parents=True, exist_ok=True)

p = pd.read_csv(a.pt / 'tracks_points_A_B_HT.csv')
s = pd.read_csv(a.pt / 'tracks_summary_A_B_HT.csv')
long_ids = s.loc[s.n_points >= a.min_len, 'track_id']
pl = p[p.track_id.isin(long_ids)].copy()
pl['green'] = pl.I_B_max >= a.thr
pl['green_above_thr'] = (pl.I_B_raw - a.thr).clip(lower=0)


def per_track(tid, g):
    g = g.sort_values('frame')
    gr = g[g.green]
    t = g.time_min.to_numpy() / 60
    slope = np.polyfit(t, g.I_B_raw, 1)[0] if len(g) > 2 and np.ptp(t) > 0 else np.nan
    return pd.Series(dict(
        n_points=len(g), start_frame=g.frame.min(), end_frame=g.frame.max(),
        green_frames=int(g.green.sum()), green_fraction=round(g.green.mean(), 3),
        first_green_frame=gr.frame.min() if len(gr) else np.nan,
        last_green_frame=gr.frame.max() if len(gr) else np.nan,
        green_max=g.I_B_max.max(), green_mean_raw=round(g.I_B_raw.mean(), 3),
        green_raw_first3=round(g.I_B_raw.head(3).mean(), 3), green_raw_last3=round(g.I_B_raw.tail(3).mean(), 3),
        green_raw_peak=round(g.I_B_raw.max(), 3),
        green_raw_slope_per_h=round(slope, 4),
        ref_raw_mean=round(g.I_A_raw.mean(), 2), ratio_BA_mean=round(g.ratio_BA.mean(), 4),
        pt_group=s.set_index('track_id').group.get(tid, '')))


summ = pd.DataFrame([dict(track_id=k, **per_track(k, g)) for k, g in pl.groupby('track_id')])
sel = summ[summ.green_frames >= a.min_green].sort_values('green_frames', ascending=False)
anyg = summ[summ.green_frames > 0]
summ.to_csv(a.out / 'long_tracks_green_summary_all.csv', index=False)
sel.to_csv(a.out / f'green_tracks_summary_thr{a.thr:g}.csv', index=False)
pl[pl.track_id.isin(sel.track_id)].to_csv(a.out / f'green_tracks_points_thr{a.thr:g}.csv', index=False)

# time courses
n = len(sel)
if n:
    cols = 4
    rows = int(np.ceil(n / cols))
    fig, axs = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.4 * rows), squeeze=False, sharex=True)
    for ax, tid in zip(axs.flat, sel.track_id):
        g = pl[pl.track_id == tid].sort_values('frame')
        h = g.time_min / 60
        ax.plot(h, g.I_B_max, 'o-', ms=3, color='#2a9d3f', label='CH0 max')
        ax.plot(h, g.I_B_raw, 's-', ms=2.5, color='#7fbf7f', label='CH0 mean')
        ax.axhline(a.thr, color='k', lw=0.8, ls='--')
        ax.set_title(f'track {tid} ({int(g.green.sum())}/{len(g)} green)', fontsize=9)
        ax.tick_params(labelsize=7)
    for ax in list(axs.flat)[n:]:
        ax.axis('off')
    axs[0, 0].legend(fontsize=7, frameon=False)
    for ax in axs[-1]:
        ax.set_xlabel('time (h)', fontsize=8)
    for ax in axs[:, 0]:
        ax.set_ylabel('CH0 (raw)', fontsize=8)
    fig.tight_layout()
    fig.savefig(a.out / f'green_tracks_timecourse_thr{a.thr:g}.png', dpi=200)
    plt.close(fig)

    # positions over the field, coloured by green frames
    fig, ax = plt.subplots(figsize=(6, 6))
    other = pl[~pl.track_id.isin(sel.track_id)]
    ax.scatter(other.x_ht, other.y_ht, s=1, c='0.8')
    for tid in sel.track_id:
        g = pl[pl.track_id == tid].sort_values('frame')
        ax.plot(g.x_ht, g.y_ht, '-', lw=1)
        ax.scatter(g.x_ht[g.green], g.y_ht[g.green], s=8, c='#2a9d3f')
        ax.annotate(str(tid), (g.x_ht.iloc[0], g.y_ht.iloc[0]), fontsize=7)
    ax.invert_yaxis()
    ax.set_aspect('equal')
    ax.set_title(f'long tracks (≥{a.min_len}) with CH0 ≥ {a.thr:g} in ≥{a.min_green} frames', fontsize=9)
    fig.tight_layout()
    fig.savefig(a.out / f'green_tracks_map_thr{a.thr:g}.png', dpi=200)
    plt.close(fig)

print(f'long tracks {len(summ)}, with green in ≥1 frame {len(anyg)}, in ≥{a.min_green} frames {len(sel)}')
print(sel.drop(columns=['ref_raw_mean']).to_string(index=False))
