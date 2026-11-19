"""QC of the signal (green) 특이 입자: drop tracks whose green vanishes abruptly or whose HT surroundings jump.

usage: <particle-tracking>/.venv/bin/python -I scripts/track_signal_qc.py PT_REPO RISEFALL_ROOT [thr]
RISEFALL_ROOT = 통합 분석/특이 입자 (ParticleTracker). Reads B …/combined (points), B …/risefall (classification),
크롭 영상 (선별 입자)/, writes '신호 있는 선별 입자 - 정제 (<n>개)/' next to them.

Criteria (per track, frames where the particle was detected):
  green loss   a clearly bright frame (green max >= 2 × thr) followed by a frame < thr, and no frame >= thr
               in the next 3 frames (the green switches off at once and does not come back)
  HT jump      normalized cross-correlation of the RI patch around the particle (31 x 31 HT px ≈ 4.8 µm) between
               consecutive detected frames below 0.1 and more than 0.35 below the track's own median correlation,
               in at least 2 frames (one odd frame is tolerated: 20 min frames, cells move and deform)
  (2026-11-19, 261118: frame-to-frame RI correlation of normal tracks is 0.2–0.6, median 0.40)
"""
import shutil
import sys
import unicodedata as ud
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ptracker.io_utils import DatasetSpec, load_stack  # noqa: E402

root = Path(sys.argv[2])
thr = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
HALF = 15
NCC_MIN, NCC_DROP, NCC_FRAMES = 0.1, 0.35, 2


def sub(name):
    return next(q for q in root.iterdir() if ud.normalize('NFC', q.name).startswith(name))


b = sub('B ')
pts = pd.read_csv(next((b / 'combined').glob('combined_tracks_points_A_B_HT*.csv')))
R = pd.read_csv(b / 'risefall' / 'risefall_classification_all_tracks.csv')
k = R[R.keep & (R.group == 'inside')]
dsmap = {}
for d in root.parent.parent.glob('*_*/*_ParticleTracker'):
    if d.name.startswith('._') or d.parent.name.startswith('._'):
        continue
    dsmap[d.parent.name.split('.A1.')[-1].split('_')[0]] = d


def ncc(a, b_):
    a = a - a.mean()
    b_ = b_ - b_.mean()
    d = np.sqrt((a * a).sum() * (b_ * b_).sum())
    return float((a * b_).sum() / d) if d > 0 else np.nan


rows, frames = [], []
for ds, kk in k.groupby('dataset'):
    spec = DatasetSpec.load(dsmap[ds] / 'dataset.json')
    HT = load_stack(spec.ri, spec.reference)
    H, W = HT.shape[1:]
    for u in kk.track_uid:
        t = pts[pts.track_uid == u].sort_values('frame')
        g = t.I_B_max.to_numpy(float)
        loss = None
        for i in range(1, len(g)):
            if g[i - 1] >= 2 * thr and g[i] < thr and np.nanmax(g[i:i + 3]) < thr:
                loss = int(t.frame.iloc[i])
                break
        cs = []
        prev = None
        for _, p in t.iterrows():
            x, y, f = int(round(p.x_ht)), int(round(p.y_ht)), int(p.frame)
            if HALF <= x < W - HALF and HALF <= y < H - HALF:
                patch = HT[f - 1, y - HALF:y + HALF + 1, x - HALF:x + HALF + 1].astype(float)
            else:
                patch = None
            if prev is not None and patch is not None and f - prev[0] <= 3:
                cs.append((f, ncc(prev[1], patch)))
                frames.append(dict(track_uid=u, frame=f, ht_ncc=cs[-1][1]))
            if patch is not None:
                prev = (f, patch)
        c = np.array([v for _, v in cs], float)
        med = float(np.nanmedian(c)) if len(c) else np.nan
        bad = [f for f, v in cs if v == v and v < NCC_MIN and (med != med or v < med - NCC_DROP)]
        rows.append(dict(dataset=ds, track_uid=u, track_id=int(u.split('::')[1]), green_loss_frame=loss,
                         ht_ncc_median=round(med, 3), ht_ncc_min=round(float(np.nanmin(c)), 3) if len(c) else np.nan,
                         ht_jump_frames=' '.join(map(str, bad)), green_loss=loss is not None, ht_jump=len(bad) >= NCC_FRAMES))
    print(ds, len(kk), flush=True)
    del HT
q = pd.DataFrame(rows)
FR = pd.DataFrame(frames).merge(pts[['track_uid', 'frame', 'I_B_max', 'I_B_raw', 'ratio_BA']], on=['track_uid', 'frame'], how='right')
FR = FR[FR.track_uid.isin(k.track_uid)].sort_values(['track_uid', 'frame'])
q['qc_keep'] = ~(q.green_loss | q.ht_jump)
q['reason'] = [', '.join(r for r, on in (('green 갑자기 사라짐', a), ('HT 주변 패턴 급변', b_)) if on) for a, b_ in
               zip(q.green_loss, q.ht_jump)]
sig_dir = sub('신호 있는 선별 입자 (')
base = pd.read_csv(sig_dir / 'signal_kept_particles.csv')
m = base.merge(q.drop(columns=['dataset', 'track_id']), on='track_uid', how='left')
n = int(m.qc_keep.sum())
out = root / f'신호 있는 선별 입자 - 정제 ({n}개)'
(out / '영상').mkdir(parents=True, exist_ok=True)
(out / '곡선').mkdir(exist_ok=True)
(out / '제외' / '영상').mkdir(parents=True, exist_ok=True)
(out / '제외' / '곡선').mkdir(exist_ok=True)
for _, r in m.iterrows():
    s = r.track_uid.replace('::', '_')
    to = out if r.qc_keep else out / '제외'
    for kind, fn in (('영상', f'crop_{s}.mp4'), ('곡선', f'trace_{s}.png')):
        src = sig_dir / kind / fn
        if src.exists():
            shutil.copy2(src, to / kind / fn)
m.round(4).to_csv(out / 'signal_kept_particles_qc.csv', index=False)
FR.round(4).to_csv(out / 'qc_per_frame.csv', index=False)
(out / 'qc_criteria.txt').write_text(__doc__, encoding='utf-8')
print(f'kept {n} / {len(m)}; green loss {int(m.green_loss.sum())}, HT jump {int(m.ht_jump.sum())}, both '
      f'{int((m.green_loss & m.ht_jump).sum())}')
print(m[['track_uid', 'category', 'green_loss_frame', 'ht_ncc_median', 'ht_ncc_min', 'ht_jump_frames', 'reason']]
      .to_string(index=False))
