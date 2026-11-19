"""Drop tracks whose green is explained by another particle passing over them (owner 2026-11-19).

usage: python scripts/track_passby.py ROOT SCORE_DIR [thr]
ROOT = folder with <image>_<ID>/<image>_ParticleTracker/; SCORE_DIR = 통합 분석/트래킹 score (from track_score.py).

For every green-on frame (ROI max >= thr) of a selected track: is another detection of that frame touching or
overlapping it (centre distance < r_self + r_other + 2 fluorescence px, ParticleTracker's particles_all_slices.csv),
and is that other particle green itself (its own ROI max >= thr in tracks_points; unknown counts as green), or is the
point flagged merged by ParticleTracker?  Those frames are 'pass-by' frames.  The green change is then judged again
with the pass-by frames left out (>= 3 clean green frames, a clean stretch of >= 2, and an on / off transition).
Tracks that no longer pass are excluded.
Writes SCORE_DIR/스쳐간 입자 제외 (<n>개)/ : 영상/ (kept), 제외/영상/, passby_per_track.csv, passby_per_frame.csv.
"""
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

root, sdir = Path(sys.argv[1]), Path(sys.argv[2])
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
GAP = 2.0

dirs = {}
for d in sorted(root.glob('*_*/*_ParticleTracker')):
    if not (d.name.startswith('._') or d.parent.name.startswith('._')):
        dirs[d.parent.name.split('.A1.')[-1].split('_')[0]] = d
sel = pd.read_csv(sdir / 'selected_reliable_green_change.csv')


def change_ok(on):
    on = np.asarray(on, bool)
    if on.sum() < 3:
        return False, ''
    idx = np.flatnonzero(on)
    run = max(len(s) for s in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1))
    rise = idx[0] > 0
    fall = idx[-1] < len(on) - 1
    kind = '켜짐→꺼짐' if rise and fall else '켜짐' if rise else '꺼짐' if fall else ''
    return bool((rise or fall) and run >= 2), kind


rows, frows = [], []
for ds, ss in sel.groupby('dataset'):
    d = dirs[ds]
    P = pd.read_csv(d / 'tracks_points_A_B_HT.csv')
    D = pd.read_csv(d / 'particles_all_slices.csv')
    gmax = P.set_index(['frame', 'roi_label']).I_B_max
    gmax = gmax[~gmax.index.duplicated()]
    byf = {f: g for f, g in D.groupby('frame')}
    for tid in ss.track_id:
        t = P[P.track_id == tid].sort_values('frame')
        on = (t.I_B_max >= thr).to_numpy()
        clean = on.copy()
        for i, (_, p) in enumerate(t.iterrows()):
            if not on[i]:
                continue
            g = byf.get(int(p.frame))
            hit, who = False, []
            if g is not None:
                r0 = float(p.radius_equiv_px)
                dd = np.hypot(g.x - p.x_fl, g.y - p.y_fl)
                near = g[(g.label != p.roi_label) & (dd < r0 + g.radius_equiv_px + GAP)]
                for _, q in near.iterrows():
                    gv = gmax.get((int(p.frame), int(q.label)), np.nan)
                    if not (gv == gv) or gv >= thr:
                        hit = True
                        who.append(f'{int(q.label)}:{"?" if gv != gv else round(float(gv), 1)}')
            if bool(p.get('merged', False)):
                hit = True
                who.append('merged')
            if hit:
                clean[i] = False
            frows.append(dict(dataset=ds, track_id=tid, frame=int(p.frame), green_max=float(p.I_B_max),
                              passby=hit, neighbours=' '.join(who)))
        ok, kind = change_ok(clean)
        n_on, n_pass = int(on.sum()), int((on & ~clean).sum())
        rows.append(dict(dataset=ds, track_id=tid, track_uid=f'{ds}::{tid}', green_frames=n_on, passby_frames=n_pass,
                         clean_green_frames=n_on - n_pass, keep=ok, kind_after=kind,
                         reason='' if ok else f'green {n_on}프레임 중 {n_pass}프레임이 다른 입자 통과 시점'))
R = sel.merge(pd.DataFrame(rows)[['track_uid', 'passby_frames', 'clean_green_frames', 'keep', 'kind_after', 'reason']],
              on='track_uid')
n = int(R.keep.sum())
out = sdir / f'스쳐간 입자 제외 ({n}개)'
(out / '영상').mkdir(parents=True, exist_ok=True)
(out / '제외' / '영상').mkdir(parents=True, exist_ok=True)
for _, r in R.iterrows():
    src = sdir / '영상' / f'crop_{r.dataset}_{r.track_id}.mp4'
    if src.exists():
        shutil.copy2(src, (out if r.keep else out / '제외') / '영상' / src.name)
R.round(4).to_csv(out / 'passby_per_track.csv', index=False)
pd.DataFrame(frows).to_csv(out / 'passby_per_frame.csv', index=False)
(out / 'passby_criteria.txt').write_text(__doc__, encoding='utf-8')
print(f'kept {n} / {len(R)}')
print(R[['track_uid', 'score', 'green_frames', 'passby_frames', 'clean_green_frames', 'keep', 'kind_after']]
      .to_string(index=False))
