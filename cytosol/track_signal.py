"""입자 추적 › 신호 기준 (owner request 2026-11-19, after the 261118 pHrodo / Cy5-PRD analysis).

Long tracks are split by whether a channel's signal reaches the LUT minimum
of that channel (the value below which the preview shows black): a track has
signal when, in at least ``frames`` of its frames, the particle ROI's maximum
(or mean) of that channel is >= the threshold.  This replaces the cell inside /
outside split of the tracks when it is on.

Values per point, in this order:
  1. the point's own ``I_<ch>_max`` (ParticleTracker measure channel) or
     ``I_<ch>_raw`` (ROI mean, every channel);
  2. ParticleTracker's ``I_B_max`` from the kept tables (projects made before
     v0.72 that tracked with the ParticleTracker method);
  3. measured on the image (per frame projection, particle outline), cached.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

BASES = (('max', '입자 ROI 최댓값'), ('mean', '입자 ROI 평균'))
MIN_LONG = 10


@dataclass
class SignalSettings:
    on: bool = False
    channel: str = ''          # channel name; '' = the tracking's measure channel
    basis: str = 'max'         # 'max' / 'mean'
    frames: int = 3            # frames at or above the threshold
    thr: float = 5.0           # = the channel's LUT minimum of the image when it is applied

    def to_dict(self):
        return asdict(self)


def measure_channel(st) -> str:
    s = st.settings or {}
    return s.get('ratio_b') or ''


def default_channel(item, st) -> str:
    ch = measure_channel(st) if st is not None else ''
    if ch in item.channels:
        return ch
    return next((c for c in item.channels if str(c) != 'RI'), item.channels[0])


def _from_points(st, ch, basis):
    key = f'I_{ch}_max' if basis == 'max' else f'I_{ch}_raw'
    if not st.points or key not in st.points[0]:
        return None
    return {(p['track_id'], p['frame']): float(p.get(key, np.nan)) for p in st.points}


def _from_pt(st, ch, basis):
    pt = getattr(st, 'pt', None)
    if not pt or basis != 'max' or ch != measure_channel(st):
        return None
    try:
        tr = pt['tr']
        return {(int(t), int(f)): float(v) for t, f, v in zip(tr['track_id'], tr['frame'], tr['I_B_max'])}
    except Exception:  # noqa: BLE001
        return None


def _measure(item, st, ch, basis, z, progress=None):
    """ROI max / mean of channel ch for every point, from the image (slow: reads each frame)."""
    from skimage.draw import polygon as fill

    from .track_panel import frame_planes
    ci = item.channels.index(ch)
    by_f = {}
    for p in st.points:
        by_f.setdefault(p['frame'], []).append(p)
    out = {}
    for n, (f, pts) in enumerate(sorted(by_f.items()), 1):
        if progress:
            progress(n, len(by_f))
        plane = frame_planes(item, f - 1, z)[ci]
        h, w = plane.shape
        for p in pts:
            loops = (st.outlines or {}).get((f, p.get('label', 0)))
            vals = None
            if loops:
                m = np.zeros((h, w), bool)
                for lp in loops:
                    rr, cc = fill(np.asarray(lp)[:, 1] - 0.5, np.asarray(lp)[:, 0] - 0.5, (h, w))
                    m[rr, cc] ^= True
                vals = plane[m]
            if vals is None or not vals.size:
                r = max(1.0, np.sqrt(max(p.get('area', 4.0), 1.0) / np.pi))
                y0, x0 = int(round(p['y'])), int(round(p['x']))
                yy, xx = np.ogrid[max(0, y0 - int(r) - 1):min(h, y0 + int(r) + 2),
                                  max(0, x0 - int(r) - 1):min(w, x0 + int(r) + 2)]
                sub = plane[yy, xx]
                vals = sub[(yy - p['y']) ** 2 + (xx - p['x']) ** 2 <= r * r]
            out[(p['track_id'], f)] = float(vals.max() if basis == 'max' else vals.mean()) if vals.size else np.nan
    return out


def point_values(item, st, ch, basis, z='mip', compute=True, progress=None):
    """(track_id, frame) -> value, or None when it would need the image and compute is False."""
    cache = getattr(st, 'signal_cache', None)
    if cache is None:
        cache = {}
        st.signal_cache = cache
    key = (ch, basis)
    if key in cache:
        return cache[key]
    v = _from_points(st, ch, basis) or _from_pt(st, ch, basis)
    if v is None:
        if not compute:
            return None
        v = _measure(item, st, ch, basis, z, progress)
    cache[key] = v
    return v


def classify(st, values, thr, frames, min_track=MIN_LONG):
    """track_id -> dict(signal, signal_frames, n, first_signal_frame, value_max, value_first3, value_last3)."""
    out = {}
    for tid, pts in st.tracks().items():
        pts = sorted(pts, key=lambda p: p['frame'])
        if len(pts) < min_track:
            continue
        v = np.array([values.get((tid, p['frame']), np.nan) for p in pts], float)
        on = v >= thr
        fr = [p['frame'] for p, o in zip(pts, on) if o]
        out[tid] = dict(signal=bool(on.sum() >= frames), signal_frames=int(on.sum()), n=len(pts),
                        signal_fraction=float(on.mean()) if len(v) else 0.0,
                        first_signal_frame=fr[0] if fr else None, last_signal_frame=fr[-1] if fr else None,
                        value_max=float(np.nanmax(v)) if np.isfinite(v).any() else np.nan,
                        value_first3=float(np.nanmean(v[:3])) if np.isfinite(v[:3]).any() else np.nan,
                        value_last3=float(np.nanmean(v[-3:])) if np.isfinite(v[-3:]).any() else np.nan)
    return out


def threshold_of(item, ch) -> float:
    return float(item.luts[item.channels.index(ch)].vmin)


# ---- outputs -------------------------------------------------------------------------

def _frame(st, values, cls, ratio):
    import pandas as pd
    rows = []
    for p in st.points:
        c = cls.get(p['track_id'])
        if c is None:
            continue
        rows.append(dict(track_id=p['track_id'], frame=p['frame'], time_min=p.get('time_min', np.nan),
                         x=p['x'], y=p['y'], signal_track=c['signal'],
                         value=values.get((p['track_id'], p['frame']), np.nan),
                         ratio=p.get(ratio, np.nan) if ratio else np.nan))
    return pd.DataFrame(rows, columns=['track_id', 'frame', 'time_min', 'x', 'y', 'signal_track', 'value', 'ratio'])


def write_item(item, st, s: SignalSettings, folder, stem, values=None, min_track=MIN_LONG):
    """<stem>_signal_tracks_summary.csv, <stem>_signal_tracks_points.csv and the comparison graphs.
    Returns (files, points DataFrame for write_all)."""
    from pathlib import Path

    import pandas as pd
    folder = Path(folder) / f'{stem}_signal_thr{s.thr:g}'
    folder.mkdir(parents=True, exist_ok=True)
    values = values if values is not None else point_values(item, st, s.channel, s.basis)
    cls = classify(st, values, s.thr, s.frames, min_track)
    summ = pd.DataFrame([dict(track_id=t, **c) for t, c in sorted(cls.items())]) if cls else \
        pd.DataFrame(columns=['track_id', 'signal', 'signal_frames', 'n'])
    files = []
    summ.to_csv(folder / f'{stem}_signal_tracks_summary.csv', index=False)
    files.append(folder / f'{stem}_signal_tracks_summary.csv')
    d = _frame(st, values, cls, st.ratio)
    d.to_csv(folder / f'{stem}_signal_tracks_points.csv', index=False)
    files.append(folder / f'{stem}_signal_tracks_points.csv')
    (folder / 'signal_settings.txt').write_text(
        f'channel {s.channel}\nbasis {s.basis}\nthreshold (LUT min) {s.thr:g}\nframes >= {s.frames}\n'
        f'long track >= {min_track} frames\n', encoding='utf-8')
    files.append(folder / 'signal_settings.txt')
    files += compare_plots(d, folder, s, title_n='')
    files += timecourse_plot(d, folder, s)
    return files, d


def compare_plots(d, folder, s: SignalSettings, title_n=''):
    """ParticleTracker-style median ± IQR: signal tracks vs the other long tracks."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    from .ptcore import plots, style
    style.setup()
    if d.empty:
        return []
    d = d.assign(t_h=d.time_min / 60)
    name = {True: f'신호 있음 ({s.channel} {"최댓값" if s.basis == "max" else "평균"} ≥ {s.thr:g}, '
                  f'{s.frames}프레임 이상)', False: '신호 없음'}
    files = []
    for var, ylab, fn in (('ratio', 'I(measure)/I(reference)', 'ratio_signal_vs_nosignal.png'),
                          ('value', f'{s.channel} {"최댓값" if s.basis == "max" else "평균"} (raw)',
                           'value_signal_vs_nosignal.png')):
        if d[var].notna().sum() == 0:
            continue
        fig, ax = plt.subplots(figsize=(10, 5.5))
        for g, c in ((True, 'tab:green'), (False, 'tab:gray')):
            q = d[d.signal_track == g].groupby('t_h')[var].quantile([.25, .5, .75]).unstack()
            if len(q):
                ax.fill_between(q.index, q[.25], q[.75], color=c, alpha=.2)
                n = d[d.signal_track == g].track_id.nunique()
                ax.plot(q.index, q[.5], '-', color=c, lw=2.5, label=f'{name[g]} (n={n}{title_n}, 중앙값 ± IQR)')
        if var == 'value':
            ax.axhline(s.thr, color='k', ls='--', lw=1, label=f'LUT 최솟값 {s.thr:g}')
        ax.set_xlabel('시간 (h)')
        ax.set_ylabel(ylab)
        ax.set_title(f'{ylab}: 신호 있음 vs 신호 없음 (긴 트랙 ≥ {MIN_LONG}프레임)')
        ax.grid(alpha=.3)
        ax.legend()
        plots._save(fig, str(folder / fn))
        files.append(folder / fn)
    return files


def timecourse_plot(d, folder, s: SignalSettings, limit=24):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    from .ptcore import plots, style
    style.setup()
    sig = d[d.signal_track]
    ids = list(sig.groupby('track_id').value.apply(lambda v: (v >= s.thr).sum()).sort_values(ascending=False).index)
    ids = ids[:limit]
    if not ids:
        return []
    cols = 4
    rows = int(np.ceil(len(ids) / cols))
    fig, axs = plt.subplots(rows, cols, figsize=(3.2 * cols, 2.4 * rows), squeeze=False, sharex=True)
    for ax, tid in zip(axs.flat, ids):
        g = sig[sig.track_id == tid].sort_values('frame')
        ax.plot(g.time_min / 60, g.value, 'o-', ms=3, color='#2a9d3f')
        ax.axhline(s.thr, color='k', lw=.8, ls='--')
        ax.set_title(f'track {tid} ({int((g.value >= s.thr).sum())}/{len(g)})', fontsize=9)
        ax.tick_params(labelsize=7)
    for ax in list(axs.flat)[len(ids):]:
        ax.axis('off')
    for ax in axs[-1]:
        ax.set_xlabel('시간 (h)', fontsize=8)
    fig.tight_layout()
    fn = folder / 'signal_tracks_timecourse.png'
    plots._save(fig, str(fn))
    return [fn]


def write_all(entries, out, s: SignalSettings):
    """entries: [(image label, DataFrame from _frame)] -> all images' graphs + per_image_summary.csv."""
    from pathlib import Path

    import pandas as pd
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    frames, rows = [], []
    for k, (label, d) in enumerate(entries, 1):
        if d.empty:
            continue
        d = d.assign(image=label, track_id=d.track_id + k * 100000)
        frames.append(d)
        n = d.track_id.nunique()
        ns = d[d.signal_track].track_id.nunique()
        rows.append(dict(image=label, long_tracks=n, signal_tracks=ns, signal_fraction=round(ns / max(n, 1), 4)))
    if not frames:
        return []
    d = pd.concat(frames, ignore_index=True)
    files = []
    d.to_csv(out / 'all_signal_tracks_points.csv', index=False)
    files.append(out / 'all_signal_tracks_points.csv')
    summ = pd.DataFrame(rows)
    tot = dict(image='전체', long_tracks=int(summ.long_tracks.sum()), signal_tracks=int(summ.signal_tracks.sum()))
    tot['signal_fraction'] = round(tot['signal_tracks'] / max(tot['long_tracks'], 1), 4)
    pd.concat([summ, pd.DataFrame([tot])], ignore_index=True).to_csv(out / 'per_image_summary.csv', index=False)
    files.append(out / 'per_image_summary.csv')
    files += compare_plots(d, out, s, title_n=f', 이미지 {len(frames)}개')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    from .ptcore import plots
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.bar(summ.image, summ.signal_fraction * 100, color='tab:green')
    for x, (n, f) in enumerate(zip(summ.signal_tracks, summ.signal_fraction)):
        ax.text(x, f * 100, str(n), ha='center', va='bottom', fontsize=8)
    ax.set_ylabel('신호 트랙 / 긴 트랙 (%)')
    ax.set_title(f'이미지별 신호 트랙 비율 (막대 위 숫자 = 트랙 수, 전체 {tot["signal_fraction"] * 100:.1f} %)')
    ax.tick_params(axis='x', labelrotation=45, labelsize=7)
    ax.grid(alpha=.3, axis='y')
    plots._save(fig, str(out / 'per_image_signal_fraction.png'))
    files.append(out / 'per_image_signal_fraction.png')
    return files
