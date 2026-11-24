"""입자 추적 › 6 신호 변화 트랙 (owner request 2026-11-19/20, mockups v073;
the 2026-11-19 analysis scripts track_score.py / track_passby.py built into
the app in v0.73).

Long tracks get a tracking score (0–100) = 100 × P(link) × P(RI):
P(link) = share of the track's links that are plain (no missed frame, not a
merged / hidden frame), P(RI) = share of consecutive frames whose RI
surroundings (≈ 4.8 µm around the particle) stay alike (correlation not
below 0.1 while 0.35 under the track's median). Among tracks scored at
least the minimum, a track whose signal (5 신호 기준: channel value ≥ the
LUT Min) turns on and / or off inside the track is a 신호 변화 트랙:
켜짐 (off → on), 꺼짐 (on → off) or 켜짐→꺼짐, with ≥ ``frames`` signal
frames and ≥ ``run`` of them in a row. Frames where another signal-on
particle touches it (centre distance < both radii + 2 px) or the point is
merged can be left out before judging (스쳐 간 입자)."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

KINDS = ('켜짐', '켜짐→꺼짐', '꺼짐')
NCC_MIN, NCC_DROP, PATCH_UM = 0.1, 0.35, 2.4


@dataclass
class ChangeSettings:
    on: bool = False
    min_score: float = 50.0
    frames: int = 3
    run: int = 2
    passby: bool = True
    inside_only: bool = True
    min_len: int = 10

    def to_dict(self):
        return asdict(self)


def _ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else np.nan


def change_kind(on, frames=3, run=2):
    """(changes, kind) of a boolean signal series."""
    on = np.asarray(on, bool)
    if on.sum() < frames:
        return False, ''
    idx = np.flatnonzero(on)
    longest = max(len(s) for s in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1))
    rise = idx[0] > 0 and not on[:idx[0]].any()
    fall = idx[-1] < len(on) - 1 and not on[idx[-1] + 1:].any()
    kind = '켜짐→꺼짐' if rise and fall else '켜짐' if rise else '꺼짐' if fall else ''
    return bool((rise or fall) and longest >= run), kind


def p_link(pts) -> float:
    n = len(pts) - 1
    if n < 1:
        return 1.0
    bad = sum(1 for p in pts[1:] if p.get('gap_before', 0) > 0 or p.get('merged'))
    return 1.0 - bad / n


def p_ri(pts, ri_of, px_um) -> tuple[float, float, int]:
    """(P(RI), median correlation, jumps): RI patches around the particle in
    consecutive frames (≤ 3 frames apart). ri_of(frame) → RI plane or None."""
    half = max(3, int(round(PATCH_UM / (px_um or 0.155))))
    cs, prev = [], None
    for p in pts:
        plane = ri_of(p['frame'])
        if plane is None:
            return 1.0, float('nan'), 0
        H, W = plane.shape
        x, y = int(round(p['x'])), int(round(p['y']))
        patch = plane[y - half:y + half + 1, x - half:x + half + 1].astype(float) \
            if half <= x < W - half and half <= y < H - half else None
        if prev is not None and patch is not None and p['frame'] - prev[0] <= 3:
            cs.append(_ncc(prev[1], patch))
        if patch is not None:
            prev = (p['frame'], patch)
    c = np.array(cs, float)
    med = float(np.nanmedian(c)) if np.isfinite(c).any() else float('nan')
    jumps = int(np.sum((c < NCC_MIN) & (c < med - NCC_DROP))) if np.isfinite(med) else 0
    return 1 - jumps / max(len(c), 1), med, jumps


def passby_frames(st, values, thr, tid, pts) -> set:
    """Frames of track tid where another signal-on particle touches it or the point is merged."""
    by_frame = {}
    for p in st.points:
        by_frame.setdefault(p['frame'], []).append(p)
    out = set()
    for p in pts:
        if p.get('merged'):
            out.add(p['frame'])
            continue
        r0 = np.sqrt(max(p.get('area', 9.0), 1.0) / np.pi)
        for q in by_frame.get(p['frame'], ()):
            if q['track_id'] == tid:
                continue
            r1 = np.sqrt(max(q.get('area', 9.0), 1.0) / np.pi)
            if np.hypot(q['x'] - p['x'], q['y'] - p['y']) < r0 + r1 + 2:
                v = values.get((q['track_id'], q['frame']), np.nan)
                if not np.isfinite(v) or v >= thr:
                    out.add(p['frame'])
                    break
    return out


def analyze(st, values, thr, s: ChangeSettings, ri_of=None, px_um=None, inside_frac=0.5) -> list:
    """One row per long track: score parts, signal frames, change kind, selected."""
    rows = []
    for tid, pts in st.tracks().items():
        pts = sorted(pts, key=lambda p: p['frame'])
        if len(pts) < s.min_len:
            continue
        pl = p_link(pts)
        pr, med, jumps = p_ri(pts, ri_of, px_um) if ri_of is not None else (1.0, float('nan'), 0)
        score = 100 * pl * pr
        v = np.array([values.get((tid, p['frame']), np.nan) for p in pts], float)
        on = v >= thr
        pb = passby_frames(st, values, thr, tid, pts) if s.passby else set()
        keep = np.array([p['frame'] not in pb for p in pts])
        ch, kind = change_kind(on[keep], s.frames, s.run) if keep.any() else (False, '')
        ch_raw, _k = change_kind(on, s.frames, s.run)
        locs = [p.get('location', '') for p in pts]
        inside = 1 - locs.count('outside') / len(pts) if any(locs) else 1.0
        ok_inside = inside > inside_frac or not s.inside_only
        idx = np.flatnonzero(on)
        rows.append(dict(track_id=tid, n=len(pts), start_frame=pts[0]['frame'], end_frame=pts[-1]['frame'],
                         p_link=pl, p_ri=pr, ri_ncc_median=med, ri_jumps=jumps, score=score,
                         signal_frames=int(on.sum()), signal_max=float(np.nanmax(v)) if np.isfinite(v).any() else np.nan,
                         first_signal_frame=pts[idx[0]]['frame'] if len(idx) else np.nan,
                         last_signal_frame=pts[idx[-1]]['frame'] if len(idx) else np.nan,
                         passby_frames=len(pb), passby_dropped=bool(ch_raw and not ch), inside_fraction=inside,
                         change=bool(ch), kind=kind if ch else '',
                         selected=bool(ch and score >= s.min_score and ok_inside)))
    return rows
