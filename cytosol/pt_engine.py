"""입자 추적 · ParticleTracker 방식 (v0.69, owner request 2026-11-18): for
Tomocube TCF files with RI and fluorescence, ParticleTracker's own pipeline
(``cytosol.ptcore``, its code unchanged) on the files' own data: reference
fluorescence at its native resolution (2DFLMIP, or the 3D stack projected),
particle detection, fluorescence → RI and reference ↔ measure registration
per frame, cells from the RI (cell body image, triangle / Otsu thresholds
from every 4th frame, IDs linked by overlap), cell flow, pattern
predictions, 2-pass appearance linking, gap closing, ROI measurement, merged
frames, track classes (dividing cells excluded).  The result becomes this
app's point rows on the RI (HT) grid the image is shown on."""

from __future__ import annotations

import json
import time
from dataclasses import replace

import numpy as np

UNIT_UM = 0.155


def is_tcf_pair(item) -> bool:
    """A TCF with an RI channel and fluorescence channels (what ParticleTracker reads)."""
    path = str(getattr(item, 'path', '') or '')
    chans = list(getattr(item, 'channels', []) or [])
    return path.lower().endswith('.tcf') and 'RI' in chans and any(str(c).startswith('CH') for c in chans)


def tcf_channel(name: str) -> str:
    """'CH1 ex635/em698' -> 'CH1' (ParticleTracker's channel name)."""
    return str(name).split(' ', 1)[0]


def config(prm, pt_k=None, gate_unit=UNIT_UM):
    """ParticleTracker Config with the 입자 추적 tab's values (µm → HT px)."""
    from .ptcore.config import Config
    cfg = Config()
    t, m = cfg.tracking, cfg.measurement
    t.gate = float(prm.gate_um / gate_unit)
    t.gate_max = float(max(prm.gate_max_um, prm.gate_um) / gate_unit)
    t.gap_max = int(prm.gap_max)
    t.gap_closing = prm.gap_max >= 1
    t.w_int, t.w_area = float(prm.w_int), float(prm.w_area)
    t.velocity_model = bool(prm.velocity)
    t.pattern_refine = bool(prm.refine)
    t.appearance = bool(prm.appearance)
    m.min_track = int(prm.min_track)
    m.inside_fraction = float(prm.inside_fraction)
    m.exclude_merged = bool(prm.exclude_merged)
    if pt_k:
        cfg.detection.k_mad = float(pt_k)
    return cfg


def _stack_3d(path, ch, ref_src, zmode):
    """(T, Y, X) of a TCF channel from its 3D data projected over Z ('mean' / 'mip')."""
    from .ptcore import io_utils as io
    src = f'{path}{io.TCF_SEP}{ch}'
    with io._h5().File(str(path), 'r') as f:
        _g2, g3 = io._tcf_groups(f, ch)
        if g3 is None or not len(g3):
            return io.load_stack(src, ref_src)
        keys = sorted(k for k in g3.keys() if k.isdigit())
        times = [float(io._attr(g3[k], 'Time', i)) for i, k in enumerate(keys)]
        ref_t = io.tcf_frame_times(ref_src) if ref_src else None
        pick = [int(np.argmin(np.abs(np.asarray(times) - t))) for t in ref_t] if ref_t else range(len(keys))
        out = []
        for i in pick:
            a = g3[keys[i]][()].astype(np.float32)
            out.append(a.mean(0) if zmode == 'mean' else a.max(0))
    return np.stack(out)


def load(path, ref_ch, mea_ch, zmode='mip'):
    """A (reference), B (measure), HT stacks as ParticleTracker reads them."""
    from .ptcore import io_utils as io
    sep = io.TCF_SEP
    ref = f'{path}{sep}{ref_ch}'
    if zmode == 'mean':
        A = _stack_3d(path, ref_ch, None, 'mean')
        B = _stack_3d(path, mea_ch, ref, 'mean')
        HT = _stack_3d(path, io.RI_CHANNEL, ref, 'mean')
    else:
        A = io.load_stack(ref)
        B = io.load_stack(f'{path}{sep}{mea_ch}', ref)
        HT = io.load_stack(f'{path}{sep}{io.RI_CHANNEL}', ref)
    return A, B, HT


def run(path, ref_ch, mea_ch, cfg, frames=None, zmode='mip', progress=None):
    """ParticleTracker's detect → register → cells → track → measure on one TCF.

    Returns dict(points (DataFrame, ParticleTracker point columns + group),
    summary, LAB, reg, S, CID, seconds per stage)."""
    from .ptcore import cells, detection, measurement, registration, tracking

    def say(msg):
        if progress:
            progress(msg)
    t0 = time.perf_counter()
    times = {}
    A, B, HT = load(path, ref_ch, mea_ch, zmode)
    if frames is not None:
        sel = list(frames)
        A, B, HT = A[sel], B[sel], HT[sel]
    S = HT.shape[1] / A.shape[1]
    times['load'] = time.perf_counter() - t0
    c = cfg
    t = time.perf_counter()
    LAB, P, _summ = detection.detect_stack(A, c.detection, lambda f, m: say(f'검출 {m}'))
    times['detect'] = time.perf_counter() - t
    t = time.perf_counter()
    reg = registration.register(A, B, HT, c.registration, lambda f, m: say(m))
    times['register'] = time.perf_counter() - t
    t = time.perf_counter()
    cim = cells.cell_body_images(HT, c.cells)
    CID, _low, _core = cells.segment_cells(cim, c.cells, lambda f, m: say(m))
    FLOW = cells.cell_flow(cim, c.cells, lambda f, m: say(m)) if c.tracking.velocity_model or True else None
    del cim
    FP, _fps = cells.footprint(HT, CID, c.footprint)
    CS = cells.mitosis_table(HT, CID, c.mitosis)
    times['cells'] = time.perf_counter() - t
    t = time.perf_counter()
    df = tracking.prepare_detections(P, reg, S, CID, FP, CS, FLOW, HT)
    df = tracking.pattern_predictions(df, A, reg, S, c.detection, c.tracking, lambda f, m: say(m))
    if c.tracking.appearance or tracking.load_learned(c.tracking):
        df = tracking.add_ht_features(df, LAB, HT, reg, S)
    LK, _AMB, PR = tracking.link_frames(df, c.tracking, lambda f, m: say(m))
    W = None
    st = tracking.link_frames.last_appearance
    if c.tracking.appearance and st:
        W = {k: v['weight_px'] for k, v in st.items() if k in tracking.APPEARANCE}
    TR, n_gap = tracking.build_tracks(df, LK, c.tracking, PR, app_w=W)
    tr = tracking.add_motion_columns(TR, c.channel.frame_interval_min)
    lk = LK.drop_duplicates('a').set_index('a')
    tr['link_margin'] = tr.idx.map(lk.margin).astype(float)
    tr['link_cost'] = tr.idx.map(lk.cost).astype(float)
    times['track'] = time.perf_counter() - t
    t = time.perf_counter()
    Bal = registration.align_b(B, reg)
    tr = measurement.measure_rois(tr, A, Bal, HT, LAB, reg, S, c.measurement, lambda f, m: say(m))
    tr = measurement.flag_merged(tr, c.measurement)
    TS = measurement.track_summary(tr, c.measurement, CS, c.channel.frame_interval_min, c.mitosis.enabled)
    tr = tr.drop(columns=[x for x in ['group'] if x in tr]).merge(TS[['track_id', 'group']], on='track_id')
    times['measure'] = time.perf_counter() - t
    times['total'] = time.perf_counter() - t0
    return dict(points=measurement.points_table(tr), summary=TS, LAB=LAB, reg=reg, S=S, CID=CID, n_gap=n_gap,
                appearance=st or {}, seconds=times, n_det=len(P))


def outlines(LAB, reg, S, keys):
    """(frame, label) -> outline loops on the RI grid (pixel-edge coordinates)."""
    from scipy import ndimage as ndi

    from .intensity import trace_outlines
    out = {}
    want = {}
    for f, lab in keys:
        want.setdefault(int(f), set()).add(int(lab))
    for f, labs in want.items():
        L = LAB[f - 1]
        dy, dx = float(reg.dy_ht.values[f - 1]), float(reg.dx_ht.values[f - 1])
        for k, sl in enumerate(ndi.find_objects(L), 1):
            if sl is None or k not in labs:
                continue
            m = L[sl] == k
            loops = trace_outlines(m, sl[1].start, sl[0].start)
            out[(f, k)] = [np.column_stack([lp[:, 0] * S + dx, lp[:, 1] * S + dy]) for lp in loops]
    return out


def to_points(res, item, chan_a, chan_b, frame0=0):
    """ParticleTracker point rows -> this app's point dicts (RI grid = the image grid)."""
    import math

    from . import tracking as tk
    px = item.pixel_um or UNIT_UM
    df = res['points']
    rows = df.to_dict('records')
    for r in rows:
        r.pop('x_fl', None)
        r.pop('y_fl', None)
    pts = tk.from_pt(rows, px, None, chan_a, chan_b)
    times = list(item.image.times) if item.image.times else None
    for p, r in zip(pts, rows):
        p['x'], p['y'] = float(r['x_ht']), float(r['y_ht'])
        p['x_um'], p['y_um'] = p['x'] * px, p['y'] * px
        p['frame'] = int(r['frame']) + frame0
        if times and p['frame'] - 1 < len(times):
            p['time_s'] = float(times[p['frame'] - 1])
            p['time_min'] = p['time_s'] / 60
        p['label'] = int(r['roi_label'])
        p['pt_group'] = str(r.get('group', ''))
        p['merged'] = bool(r.get('merged', False))
        S = res['S']
        p['area'] = float(r['area_px'])                     # fluorescence px
        p['area_um2'] = p['area'] * (px / S) ** 2 if S else p['area'] * px * px
        p['pat_score'] = float(r.get('pat_score', float('nan')))
        p['gate_um'] = float(r.get('gate_used', float('nan'))) * px
        p['link_cost'] = float(r.get('link_cost', float('nan')))
        p['link_margin'] = float(r.get('link_margin', float('nan')))
        p['ri_mean'], p['ri_max'] = float(r.get('HT_RI_mean', float('nan'))), float(r.get('HT_RI_max', float('nan')))
        for k_ht, k in (('step_ht', 'step_um'), ('cell_carried_ht', 'cell_carried_um'), ('residual_ht', 'residual_um')):
            v = r.get(k_ht, float('nan'))
            p[k] = float(v) * px if v == v else float('nan')
    pts.sort(key=lambda p: (p['track_id'], p['frame']))
    prev = None
    for p in pts:
        p['gap_before'] = int(p['frame'] - prev['frame'] - 1) if prev is not None and prev['track_id'] == p['track_id'] else 0
        if p.get('step_um') != p.get('step_um') and prev is not None and prev['track_id'] == p['track_id']:
            p['step_um'] = math.hypot(p['x'] - prev['x'], p['y'] - prev['y']) * px
        prev = p
    return pts


def appearance_text(st) -> str:
    return json.dumps({k: round(v.get('weight_px', 0), 3) for k, v in (st or {}).items() if isinstance(v, dict)
                       and 'weight_px' in v}, ensure_ascii=False)


def with_detection(cfg, **kw):
    cfg.detection = replace(cfg.detection, **kw)
    return cfg
