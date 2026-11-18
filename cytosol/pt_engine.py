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
    LAB, P, summ = detection.detect_stack(A, c.detection, lambda f, m: say(f'검출 {m}'))
    times['detect'] = time.perf_counter() - t
    t = time.perf_counter()
    reg = registration.register(A, B, HT, c.registration, lambda f, m: say(m))
    times['register'] = time.perf_counter() - t
    t = time.perf_counter()
    cim = cells.cell_body_images(HT, c.cells)
    CID, _low, _core = cells.segment_cells(cim, c.cells, lambda f, m: say(m))
    FLOW = cells.cell_flow(cim, c.cells, lambda f, m: say(m)) if c.tracking.velocity_model or True else None
    del cim
    FP, fps = cells.footprint(HT, CID, c.footprint)
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
    dt = c.channel.frame_interval_min
    pc = measurement.per_cell(tr, CID, dt)
    CI = measurement.cell_intensity(A, Bal, CID, reg, S, dt)
    times['measure'] = time.perf_counter() - t
    times['total'] = time.perf_counter() - t0
    pt = dict(P=P, summ=summ, reg=reg, fps=fps, CS=CS, TS=TS, tr=tr, pc=pc, CI=CI, cfg=c.to_dict(), S=float(S),
              appearance=st or {}, arrays=_pack(LAB=LAB, CID=CID, FP=FP), zmode=zmode,
              frames=list(frames) if frames is not None else None,
              sources=dict(reference=f'{path}::{ref_ch}', measure=f'{path}::{mea_ch}', ri=f'{path}::RI'))
    return dict(points=measurement.points_table(tr), summary=TS, LAB=LAB, reg=reg, S=S, CID=CID, n_gap=n_gap,
                appearance=st or {}, seconds=times, n_det=len(P), pt=pt)


def _pack(**arrays) -> bytes:
    import io
    b = io.BytesIO()
    np.savez_compressed(b, **arrays)
    return b.getvalue()


def _unpack(data: bytes) -> dict:
    import io
    with np.load(io.BytesIO(data)) as z:
        return {k: z[k] for k in z.files}


def _yaml(d: dict) -> str:
    """config_used.yaml as ParticleTracker writes it (yaml.safe_dump of two levels of scalars)."""
    def sc(v):
        if isinstance(v, bool):
            return 'true' if v else 'false'
        if isinstance(v, (int, float)):
            return repr(v)
        v = str(v)
        return "''" if v == '' else (repr(v) if any(ch in v for ch in ':#{}[],&*!|>\'"%@`') else v)
    out = []
    for sec, vals in d.items():
        out.append(f'{sec}:')
        for k, v in vals.items():
            out.append(f'  {k}: {sc(v)}')
    return '\n'.join(out) + '\n'


# ParticleTracker result files (pipeline.DatasetRunner stages detect … measure, figures, movies)
PT_FILES = ('dataset.json', 'config_used.yaml', 'particles_all_slices.csv', 'summary_per_slice.csv',
            'particle_labels.tif', 'registration.csv', 'footprint_per_frame.csv', 'cell_stats_mitosis.csv',
            'tracking_appearance_weights.json', 'tracks_summary_A_B_HT.csv', 'tracks_points_A_B_HT.csv',
            'particles_per_cell.csv', 'cell_intensity.csv')


def write_outputs(pt: dict, folder, name: str, figures=True, movies=False, progress=None) -> list:
    """ParticleTracker's result folder (same file names, columns and rounding) from a run of this engine."""
    import tifffile
    from pathlib import Path

    from .ptcore import measurement
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    files = []

    def put(fn):
        files.append(out / fn)
    src = pt['sources']
    (out / 'dataset.json').write_text(json.dumps(dict(name=name, reference=src['reference'], measure=src['measure'],
                                                      ri=src['ri'], out_dir=str(out)), ensure_ascii=False, indent=1),
                                      encoding='utf-8')
    put('dataset.json')
    (out / 'config_used.yaml').write_text(_yaml(pt['cfg']), encoding='utf-8')
    put('config_used.yaml')
    pt['P'].round(3).to_csv(out / 'particles_all_slices.csv', index=False)
    put('particles_all_slices.csv')
    pt['summ'].round(3).to_csv(out / 'summary_per_slice.csv', index=False)
    put('summary_per_slice.csv')
    arr = _unpack(pt['arrays'])
    LAB = arr['LAB']
    tifffile.imwrite(out / 'particle_labels.tif', LAB, imagej=LAB.dtype == np.uint16)
    put('particle_labels.tif')
    pt['reg'].round(4).to_csv(out / 'registration.csv', index=False)
    put('registration.csv')
    pt['fps'].round(4).to_csv(out / 'footprint_per_frame.csv', index=False)
    put('footprint_per_frame.csv')
    pt['CS'].round(3).to_csv(out / 'cell_stats_mitosis.csv', index=False)
    put('cell_stats_mitosis.csv')
    if pt.get('appearance'):
        (out / 'tracking_appearance_weights.json').write_text(json.dumps(pt['appearance'], indent=1, ensure_ascii=False),
                                                              encoding='utf-8')
        put('tracking_appearance_weights.json')
    pt['TS'].round(5).to_csv(out / 'tracks_summary_A_B_HT.csv', index=False)
    put('tracks_summary_A_B_HT.csv')
    measurement.points_table(pt['tr']).round(4).to_csv(out / 'tracks_points_A_B_HT.csv', index=False)
    put('tracks_points_A_B_HT.csv')
    pt['pc'].round(5).to_csv(out / 'particles_per_cell.csv', index=False)
    put('particles_per_cell.csv')
    pt['CI'].round(5).to_csv(out / 'cell_intensity.csv', index=False)
    put('cell_intensity.csv')
    if figures or movies:
        files += _figures_movies(pt, arr, out, figures, movies, progress)
    return files


def _figures_movies(pt, arr, out, figures, movies, progress=None):
    """ParticleTracker's stage_figures / stage_movies (the raw stacks are read again from the TCF)."""
    import pandas as pd

    from .ptcore import movies as mv
    from .ptcore import plots, registration
    from .ptcore.io_utils import split_source
    path, ref = split_source(pt['sources']['reference'])
    mea = split_source(pt['sources']['measure'])[1]
    A, B, HT = load(path, ref, mea, pt.get('zmode') or 'mip')
    if pt.get('frames') is not None:
        A, B, HT = A[pt['frames']], B[pt['frames']], HT[pt['frames']]
    CID, FP = arr['CID'], arr['FP']
    tr, reg, CS, S = pt['tr'], pt['reg'], pt['CS'], pt['S']
    o = str(out)
    files = []
    if figures:
        long = tr[tr.group.isin(['inside', 'outside'])]
        before = set(out.glob('*.png'))
        plots.ratio_figures(long, o)
        plots.qc_detection_cells(A, pt['P'], HT, CID, f'{o}/qc_detection_and_cells.png')
        plots.tracks_overlay(HT, CID, long, f'{o}/tracks_overlay.png')
        plots.regions_figure(HT, CID, FP, CS, f'{o}/regions_cytoplasm_spread_membrane.png')
        plots.mitosis_figure(CS, f'{o}/mitosis_detection.png')
        plots.cell_timecourses(pd.read_csv(out / 'cell_intensity.csv'), f'{o}/cell_intensity_timecourse.png')
        files += sorted(set(out.glob('*.png')) - before) or sorted(out.glob('*.png'))
    if movies:
        dt = pt['cfg']['channel']['frame_interval_min']
        fps = pt['cfg']['output']['movie_fps']
        Bal = registration.align_b(B, reg)
        d = tr[tr.group.isin(['inside', 'outside', 'excluded_mitotic'])]
        jobs = [('RI_regions', HT, False, d, dict(cellmask_fp=FP, CS=CS))]
        for g in ['inside', 'outside']:
            dg = d[d.group == g]
            col = plots._track_colors(dg.track_id.unique())
            jobs += [(f'reference_{g}', A, True, dg, dict(colors=col)), (f'measure_{g}', Bal, True, dg, dict(colors=col)),
                     (f'RI_{g}', HT, False, dg, dict(colors=col))]
        for i, (nm, st, fl, pts, kw) in enumerate(jobs):
            if progress:
                progress(f'영상 {nm} ({i + 1}/{len(jobs)})')
            files.append(mv.channel_movie(st, pts, str(out / f'movie_{nm}'), fl, S, CID, reg, dt, nm, fps, **kw))
    return files


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


def app_tables(st, item, summary_rows, prm):
    """ParticleTracker point and track tables from tracks made by this app's
    own method (ParticleTracker columns; columns it has no value for stay empty)."""
    import pandas as pd

    from .ptcore import measurement
    from .ptcore.config import MeasurementParams
    px = item.pixel_um or UNIT_UM
    a, b = (st.ratio[len('ratio_'):].split('_', 1)[::-1] if st.ratio else ('', ''))
    a = prm.get('ratio_a') or a
    b = prm.get('ratio_b') or b
    cls = {r['track_id']: r['class'] for r in summary_rows}
    nan = float('nan')
    rows = []
    for p in st.points:
        g = lambda k: p.get(k, nan)  # noqa: E731
        ia, ib = g(f'I_{a}'), g(f'I_{b}')
        ratio = g(st.ratio) if st.ratio else nan
        rows.append(dict(
            track_id=p['track_id'], group=cls.get(p['track_id'], ''), frame=p['frame'], time_min=g('time_min'),
            label=p.get('label', 0), x=p['x'], y=p['y'], x_ht=p['x'], y_ht=p['y'], cell_id=int(p.get('cell', 0)),
            inside_cell=p.get('loc', 'outside') != 'outside',
            region='cytoplasm' if p.get('loc', 'outside') != 'outside' else 'background',
            on_footprint=False, in_mitotic_cell=False, ht_confirmed=False, pat_score=g('pat_score'),
            pat2_score=nan, pat_refined=False, gate_used=g('gate_um') / px, area_px=g('area'),
            radius_equiv_px=float(np.sqrt(g('area') / np.pi)) if g('area') == g('area') else nan,
            eccentricity=g('ecc'), mean_intensity=g('mean'),
            I_A_raw=g(f'I_{a}_raw'), bg_A=g(f'bg_{a}'), I_A=ia, I_B_raw=g(f'I_{b}_raw'), bg_B=g(f'bg_{b}'), I_B=ib,
            I_B_max=nan, ratio_BA=ratio, ratio_BA_raw=(g(f'I_{b}_raw') / g(f'I_{a}_raw')) if g(f'I_{a}_raw') else nan,
            merged=bool(p.get('merged', False)), ratio_BA_unfiltered=g(f'{st.ratio}_unfiltered') if st.ratio else nan,
            HT_RI_mean=g('ri_mean'), HT_RI_max=g('ri_max'),
            step_ht=g('step_um') / px, cell_carried_ht=g('cell_carried_um') / px, residual_ht=g('residual_um') / px,
            link_margin=g('link_margin'), link_cost=g('link_cost')))
    tr = pd.DataFrame(rows)
    mp = MeasurementParams()
    mp.min_track, mp.inside_fraction = int(prm.get('min_track', mp.min_track)), float(prm.get('inside_fraction', 0.5))
    CS = pd.DataFrame({'cell_id': pd.Series(dtype=int), 'frame': pd.Series(dtype=int), 'mitotic': pd.Series(dtype=bool)})
    times = sorted({(p['frame'], p.get('time_min', 0)) for p in st.points})
    dt = float(np.median(np.diff([t for _, t in times]))) if len(times) > 1 else 1.0
    TS = measurement.track_summary(tr, mp, CS, dt, False) if len(tr) else pd.DataFrame()
    P = tr[['frame', 'label', 'y', 'x', 'area_px', 'eccentricity', 'mean_intensity', 'radius_equiv_px']].copy()
    P['integrated_intensity'] = P.area_px * P.mean_intensity
    P['perimeter'] = P['max_intensity'] = P['min_intensity'] = nan
    P = P[['frame', 'label', 'y', 'x', 'area_px', 'perimeter', 'eccentricity', 'mean_intensity', 'max_intensity',
           'min_intensity', 'radius_equiv_px', 'integrated_intensity']]
    summ = P.groupby('frame').agg(n_particles=('label', 'size'), median_area_px=('area_px', 'median'),
                                  median_radius_px=('radius_equiv_px', 'median'),
                                  median_mean_intensity=('mean_intensity', 'median')).reset_index()
    summ.insert(1, 'threshold', nan)
    pc = tr[tr.cell_id > 0].groupby(['cell_id', 'frame']).agg(
        n_particles=('track_id', 'size'), median_ratio_BA=('ratio_BA', 'median'), sum_I_A=('I_A', 'sum'),
        sum_I_B=('I_B', 'sum')).reset_index()
    pc['time_min'] = (pc.frame - 1) * dt
    pc.insert(2, 'cell_area_htpx', nan)
    return dict(tr=tr, TS=TS, P=P, summ=summ, pc=pc, a=a, b=b)


def write_app_outputs(st, item, summary_rows, folder, name: str) -> list:
    """ParticleTracker's file names and columns for tracks of this app's method:
    tracks_points / tracks_summary_A_B_HT.csv, particles_all_slices.csv,
    summary_per_slice.csv, particles_per_cell.csv, dataset.json, config_used.yaml."""
    from pathlib import Path

    from .ptcore import measurement
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    prm = st.settings or {}
    t = app_tables(st, item, summary_rows, prm)
    p = str(item.path)
    (out / 'dataset.json').write_text(json.dumps(dict(name=name, reference=f'{p}::{t["a"]}', measure=f'{p}::{t["b"]}',
                                                      ri=f'{p}::RI' if 'RI' in item.channels else '', out_dir=str(out),
                                                      method='Cytosol Viewer 입자 추적'),
                                                 ensure_ascii=False, indent=1), encoding='utf-8')
    (out / 'config_used.yaml').write_text(_yaml({'cytosol_viewer_tracking': prm}), encoding='utf-8')
    t['P'].round(3).to_csv(out / 'particles_all_slices.csv', index=False)
    t['summ'].round(3).to_csv(out / 'summary_per_slice.csv', index=False)
    t['TS'].round(5).to_csv(out / 'tracks_summary_A_B_HT.csv', index=False)
    measurement.points_table(t['tr']).round(4).to_csv(out / 'tracks_points_A_B_HT.csv', index=False)
    t['pc'].round(5).to_csv(out / 'particles_per_cell.csv', index=False)
    return [out / f for f in ('dataset.json', 'config_used.yaml', 'particles_all_slices.csv', 'summary_per_slice.csv',
                              'tracks_summary_A_B_HT.csv', 'tracks_points_A_B_HT.csv', 'particles_per_cell.csv')]
