"""Tracking score of every long track, and the reliable tracks whose green rises / falls (owner 2026-11-19).

usage: <particle-tracking>/.venv/bin/python -I scripts/track_score.py PT_REPO ROOT OUT [thr] [--crops]
ROOT holds <image>_<ID>/<image>_ParticleTracker/ (ParticleTracker result folders).

Score (0–100) of a track = 100 × P(link) × P(HT), where
  P(link) = ParticleTracker's reliability of the whole track (reliability.window_reliability: every link correct,
            from the link margins; gaps and merged frames lower it),
  P(HT)   = fraction of consecutive detected frames whose RI surroundings (31 × 31 HT px ≈ 4.8 µm around the particle)
            stay alike: correlation not (< 0.1 and > 0.35 below the track's median).
Reliable = score ≥ 50 (cut written in the output; change with SCORE_MIN).
Green change (measure channel = green, ROI max): ≥ 3 frames ≥ thr AND the track has frames below thr before the
first or after the last green frame (the green turns on and / or off inside the track), and the green-on stretch
is at least 2 consecutive frames.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ptracker import reliability  # noqa: E402
from ptracker.io_utils import DatasetSpec, load_stack  # noqa: E402

root, out = Path(sys.argv[2]), Path(sys.argv[3])
thr = float(sys.argv[4]) if len(sys.argv) > 4 and not sys.argv[4].startswith('--') else 5.0
CROPS = '--crops' in sys.argv
SCORE_MIN = float(os.environ.get('SCORE_MIN', 50))
MIN_LEN, HALF, NCC_MIN, NCC_DROP = 10, 15, 0.1, 0.35
out.mkdir(parents=True, exist_ok=True)

dirs = {}
for d in sorted(root.glob('*_*/*_ParticleTracker')):
    if d.name.startswith('._') or d.parent.name.startswith('._'):
        continue
    if (d / 'tracks_points_A_B_HT.csv').exists():
        dirs[d.parent.name.split('.A1.')[-1].split('_')[0]] = d
perr, why = reliability.calibrate(list(dirs.values()))
print('link error rates:', why, flush=True)


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else np.nan


def green_change(g):
    on = g >= thr
    if on.sum() < 3:
        return False, ''
    idx = np.flatnonzero(on)
    run = max(len(s) for s in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1))
    rise = idx[0] > 0 and not on[:idx[0]].any()
    fall = idx[-1] < len(g) - 1 and not on[idx[-1] + 1:].any()
    kind = '켜짐→꺼짐' if rise and fall else '켜짐' if rise else '꺼짐' if fall else ''
    return bool((rise or fall) and run >= 2), kind


rows, all_pts = [], []
for ds, d in dirs.items():
    P = pd.read_csv(d / 'tracks_points_A_B_HT.csv')
    n = P.groupby('track_id').frame.transform('size')
    P = P[n >= MIN_LEN]
    spec = DatasetSpec.load(d / 'dataset.json')
    HT = load_stack(spec.ri, spec.reference)
    H, W = HT.shape[1:]
    for tid, t in P.groupby('track_id'):
        t = t.sort_values('frame')
        rel = reliability.window_reliability(t, t.frame.min(), t.frame.max() + 1, perr)
        cs, prev = [], None
        for x, y, f in zip(t.x_ht.round().astype(int), t.y_ht.round().astype(int), t.frame.astype(int)):
            patch = HT[f - 1, y - HALF:y + HALF + 1, x - HALF:x + HALF + 1].astype(float) \
                if HALF <= x < W - HALF and HALF <= y < H - HALF else None
            if prev is not None and patch is not None and f - prev[0] <= 3:
                cs.append(ncc(prev[1], patch))
            if patch is not None:
                prev = (f, patch)
        c = np.array(cs, float)
        med = float(np.nanmedian(c)) if np.isfinite(c).any() else np.nan
        jumps = int(np.sum((c < NCC_MIN) & (c < med - NCC_DROP))) if np.isfinite(med) else 0
        p_ht = 1 - jumps / max(len(c), 1)
        g = t.I_B_max.to_numpy(float)
        ch, kind = green_change(g)
        on = np.flatnonzero(g >= thr)
        rows.append(dict(dataset=ds, track_id=int(tid), track_uid=f'{ds}::{tid}', group=t.group.iloc[0], n=len(t),
                         start_frame=int(t.frame.min()), end_frame=int(t.frame.max()),
                         p_link=rel['reliability'], risky_links=rel['risky_links'], gap_links=rel['gap_links'],
                         merged_frames=rel['merged_frames'], min_margin=rel['min_margin'],
                         ht_ncc_median=med, ht_jumps=jumps, p_ht=p_ht, score=100 * rel['reliability'] * p_ht,
                         green_frames=int((g >= thr).sum()), green_max=float(np.nanmax(g)),
                         first_green_frame=int(t.frame.iloc[on[0]]) if len(on) else np.nan,
                         last_green_frame=int(t.frame.iloc[on[-1]]) if len(on) else np.nan,
                         green_change=ch, green_change_kind=kind,
                         ratio_first3=float(t.ratio_BA.head(3).mean()), ratio_last3=float(t.ratio_BA.tail(3).mean()),
                         ratio_max=float(t.ratio_BA.max())))
    print(ds, len(P.track_id.unique()), 'long tracks', flush=True)
    t2 = P.copy()
    t2.insert(0, 'dataset', ds)
    all_pts.append(t2)
    del HT
S = pd.DataFrame(rows)
S['reliable'] = S.score >= SCORE_MIN
S['selected'] = S.reliable & S.green_change
S.round(4).to_csv(out / 'track_scores_all_long_tracks.csv', index=False)
sel = S[S.selected].sort_values('score', ascending=False)
sel.round(4).to_csv(out / 'selected_reliable_green_change.csv', index=False)
(out / 'score_criteria.txt').write_text(__doc__ + f'\nlink error rates: {why}\nSCORE_MIN {SCORE_MIN}\n', encoding='utf-8')

import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

from ptracker import plots, style  # noqa: E402
style.setup()
fig, ax = plt.subplots(1, 2, figsize=(12, 4.5))
ax[0].hist(S.score, bins=50, color='0.5')
ax[0].axvline(SCORE_MIN, color='r', ls='--')
ax[0].set_xlabel('트래킹 score')
ax[0].set_ylabel('긴 트랙 수')
ax[0].set_title(f'긴 트랙 {len(S)}개 · score ≥ {SCORE_MIN:g}: {int(S.reliable.sum())}개')
ax[1].scatter(S.score, S.green_frames, s=4, c=np.where(S.selected, 'tab:green', '0.6'))
ax[1].set_xlabel('트래킹 score')
ax[1].set_ylabel(f'green ≥ {thr:g} 프레임 수')
ax[1].set_title(f'선택 (score ≥ {SCORE_MIN:g} + green 증감): {len(sel)}개')
plots._save(fig, str(out / 'track_score_overview.png'))

P = pd.concat(all_pts, ignore_index=True)
P['track_uid'] = P.dataset + '::' + P.track_id.astype(str)
ids = list(sel.track_uid)[:48]
if ids:
    cols = 4
    rws = int(np.ceil(len(ids) / cols))
    fig, axs = plt.subplots(rws, cols, figsize=(3.6 * cols, 2.6 * rws), squeeze=False, sharex=True)
    for a, u in zip(axs.flat, ids):
        t = P[P.track_uid == u].sort_values('frame')
        h = (t.frame - 1) * 20 / 60
        a.plot(h, t.I_B_max, 'o-', ms=2.5, color='#2a9d3f')
        a.axhline(thr, color='k', lw=.7, ls='--')
        a2 = a.twinx()
        a2.plot(h, t.ratio_BA, '-', color='tab:purple', lw=1)
        a2.tick_params(labelsize=6)
        r = sel[sel.track_uid == u].iloc[0]
        a.set_title(f'{u}  score {r.score:.0f}  {r.green_change_kind}', fontsize=8)
        a.tick_params(labelsize=7)
    for a in list(axs.flat)[len(ids):]:
        a.axis('off')
    fig.suptitle('선택 트랙: 초록 = green ROI 최댓값 (왼쪽 축, 점선 = 기준), 보라 = I(measure)/I(reference) (오른쪽 축)')
    fig.tight_layout()
    plots._save(fig, str(out / 'selected_traces.png'))
print(f'long tracks {len(S)}, reliable {int(S.reliable.sum())}, green change {int(S.green_change.sum())}, '
      f'selected {len(sel)}', flush=True)
print(sel.groupby('dataset').size().to_dict(), sel.green_change_kind.value_counts().to_dict(), flush=True)

if CROPS and len(sel):
    from ptracker import movies, registration
    from ptracker.io_utils import load_dataset
    cdir = out / '영상'
    cdir.mkdir(exist_ok=True)
    for ds, rr in sel.groupby('dataset'):
        spec = DatasetSpec.load(dirs[ds] / 'dataset.json')
        A, B, HT = load_dataset(spec)
        Bal = registration.align_b(B, pd.read_csv(dirs[ds] / 'registration.csv'))
        for u in rr.track_uid:
            t = P[P.track_uid == u]
            r = rr[rr.track_uid == u].iloc[0]
            info = f'{ds} | {r.track_id} | score {r.score:.0f} | green {r.green_change_kind}'
            try:
                movies.crop_movie(A, Bal, HT, t, HT.shape[1] / A.shape[1], str(cdir / f'crop_{ds}_{r.track_id}'), info,
                                  None, 32, 3, {})
            except Exception as e:  # noqa: BLE001
                print('crop failed', u, e, flush=True)
        print('crops', ds, len(rr), flush=True)
        del A, B, HT, Bal
print('done', flush=True)
