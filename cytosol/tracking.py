"""입자 추적 (v0.66): particles detected on every frame, linked between frames
and measured, ported from ParticleTracker 1.11 (tracking.py, measurement.py)
without pandas, in image pixels with distances given in µm.

Linking (TrackMate LAP tracker style; Jaqaman et al., 2008): a predicted
position for every particle of frame t (cell movement by optical flow of the
cell channel + template matching of the particle and its neighbourhood in
the next frame (two template sizes) + the track's own velocity by an α-β
filter, with a gate that widens with the track's prediction error), a cost
matrix (distance + cell mismatch + |ln intensity ratio| + |ln area ratio| +
deviation from the neighbours' median movement, second pass), one-to-one
assignment by linear assignment with termination costs, and gap closing over
up to ``gap_max`` missing frames by a second assignment over track ends and
starts.

Measurement: the mean of each particle ROI minus the median of a ring around
it (other particles left out of the ring), per channel; ratio of two chosen
channels; points where the particle merged with another one (area and total
reference intensity jump together) are flagged and left out of the ratio.

Costs are in ParticleTracker's units (one HT pixel, ``UNIT_UM``), so its
weights keep their meaning.
"""

from __future__ import annotations

import csv
import math
from dataclasses import asdict, dataclass, field, fields

import numpy as np

UNIT_UM = 0.155        # ParticleTracker's cost unit: one TCF HT pixel


@dataclass
class TrackSettings:
    cells: str = 'static'          # 'static' (the image's cell ROIs) or 'frame' (detected per frame, IDs linked)
    flow: bool = True              # cell movement by optical flow of the cell channel
    pattern: bool = True           # template matching prediction
    velocity: bool = True          # α-β track velocity + adaptive gate
    gate_um: float = 1.55
    gate_max_um: float = 2.48       # ParticleTracker: 16 HT px
    gate_k: float = 4.0
    vel_alpha: float = 0.4
    w_cell: float = 2.0
    w_int: float = 3.0
    w_area: float = 1.5
    w_nb: float = 1.0
    nb_radius_um: float = 2.8
    nb_min: int = 2
    pattern_half_um: float = 1.7
    pattern_search_um: float = 1.35
    score_hi: float = 0.5
    score_lo: float = 0.4
    refine: bool = True
    refine_half_um: float = 0.56
    refine_search_um: float = 2.7
    refine_min: float = 0.5
    refine_weight: float = 0.5
    gap_max: int = 2               # owner 2026-11-18: 2 (ParticleTracker's default is 1)
    gap_penalty: float = 1.0
    ring_in: int = 3               # px; used only when the pixel size is unknown
    ring_out: int = 8
    ring_in_um: float = 0.34       # ParticleTracker: 3 / 8 fluorescence px of 0.112 µm
    ring_out_um: float = 0.9
    appearance: bool = True        # ParticleTracker 2-pass appearance weights (needs an RI channel)
    appearance_scale: float = 1.0
    min_ia: float = 5.0
    min_track: int = 10
    inside_fraction: float = 0.5
    merge_area_ratio: float = 1.8
    merge_int_ratio: float = 1.6
    merge_max_frames: int = 3
    exclude_merged: bool = True
    ratio_b: str = ''              # ratio = I_<ratio_b> / I_<ratio_a> (channel names, '' = none)
    ratio_a: str = ''
    engine: str = 'pt'             # TCF RI + fluorescence: 'pt' = ParticleTracker's own pipeline (pt_engine)
    z_project: str = 'mip'         # Z stacks: 'mip' / 'mean' projection per frame, '' = the viewer's Z

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name: f for f in fields(cls)}
        out = cls()
        for k, v in (d or {}).items():
            if k in names:
                try:
                    setattr(out, k, type(getattr(out, k))(v))
                except (TypeError, ValueError):
                    pass
        return out


# ---------------------------------------------------------------------------
# detections
# ---------------------------------------------------------------------------

DET_KEYS = ('frame', 'label', 'y', 'x', 'area', 'mean', 'ecc', 'cell', 'loc')


def ring_px(prm: TrackSettings, px_um=None):
    """(inner, outer) background ring in pixels of this image."""
    if not px_um:
        return prm.ring_in, prm.ring_out
    a = max(0, int(round(prm.ring_in_um / px_um)))
    return a, max(a + 1, int(round(prm.ring_out_um / px_um)))


def frame_detections(frame, labels, planes, channels, det_channel, cell_labels, nuclei, prm: TrackSettings,
                     px_um=None):
    """Detections of one frame (1-based) from its particle label image: centre
    (intensity weighted), area, mean of the detection channel, eccentricity,
    cell and location, and per channel the ROI mean, ring median and their
    difference. Also the outlines (for drawing / ROI files)."""
    from scipy import ndimage as ndi
    from skimage import measure

    from .intensity import trace_outlines

    rows, outlines = [], []
    if labels is None or not labels.max():
        return rows, outlines
    det = planes[det_channel].astype(np.float32)
    H, W = labels.shape
    r_in, r_out = ring_px(prm, px_um)
    se_i = np.ones((2 * r_in + 1,) * 2, bool)
    se_o = np.ones((2 * r_out + 1,) * 2, bool)
    pad = r_out + 2
    ri = next((c for c, n in enumerate(channels) if str(n).upper() == 'RI'), None)
    occ = ndi.binary_dilation(labels > 0, iterations=2)
    for r in measure.regionprops(labels, intensity_image=det):
        k = r.label
        sl = r.slice
        y0, y1 = max(sl[0].start - pad, 0), min(sl[0].stop + pad, H)
        x0, x1 = max(sl[1].start - pad, 0), min(sl[1].stop + pad, W)
        m = labels[y0:y1, x0:x1] == k
        ring = ndi.binary_dilation(m, se_o) & ~ndi.binary_dilation(m, se_i) & ~occ[y0:y1, x0:x1]
        ok = ring.sum() > 10
        w = np.clip(det[y0:y1, x0:x1][m], 0, None)
        yy, xx = np.nonzero(m)
        if w.sum() > 0:
            cy, cx = float((yy * w).sum() / w.sum()) + y0, float((xx * w).sum() / w.sum()) + x0
        else:
            cy, cx = float(yy.mean()) + y0, float(xx.mean()) + x0
        iy, ix = min(int(round(cy)), H - 1), min(int(round(cx)), W - 1)
        cell = int(cell_labels[iy, ix]) if cell_labels is not None else 0
        if cell == 0:
            loc = 'outside'
        elif nuclei is not None and nuclei[iy, ix] > 0:
            loc = 'nucleus'
        else:
            loc = 'cytosol'
        row = dict(frame=frame, label=k, y=cy, x=cx, area=int(r.area), mean=float(det[r.slice][r.image].mean()),
                   ecc=float(r.eccentricity) if r.area > 2 else 0.0, cell=cell, loc=loc)
        if ri is not None:   # RI of the ROI (ParticleTracker's appearance features)
            v = planes[ri][y0:y1, x0:x1][m]
            row['ri_mean'], row['ri_max'] = float(v.mean()), float(v.max())
        for c, name in enumerate(channels):
            v = planes[c][y0:y1, x0:x1].astype(np.float64)
            raw = float(v[m].mean())
            bg = float(np.median(v[ring])) if ok else float('nan')
            row[f'I_{name}_raw'] = raw
            row[f'bg_{name}'] = bg
            row[f'I_{name}'] = raw - bg if ok else float('nan')
        rows.append(row)
        outlines.append(trace_outlines(m, x0, y0))
    return rows, outlines


def as_columns(rows, keys=None):
    keys = keys or (list(rows[0]) if rows else list(DET_KEYS))
    out = {}
    for k in keys:
        vals = [r.get(k) for r in rows]
        out[k] = np.asarray(vals, dtype=object if k == 'loc' else float)
    return out


# ---------------------------------------------------------------------------
# prediction: cell flow and template matching
# ---------------------------------------------------------------------------

def cell_flow(a, b, step=4):
    """(2, H, W) movement of the cell image from a to b (TV-L1 optical flow at 1/step)."""
    from skimage.registration import optical_flow_tvl1
    from skimage.transform import resize
    H, W = a.shape
    h, w = max(H // step, 8), max(W // step, 8)
    lo, hi = np.percentile(a, [1, 99.5])
    d = max(hi - lo, 1e-6)
    aa = resize((a - lo) / d, (h, w), anti_aliasing=True)
    bb = resize((b - lo) / d, (h, w), anti_aliasing=True)
    v, u = optical_flow_tvl1(aa, bb, attachment=10.0)
    return np.stack([resize(v, (H, W)) * (H / h), resize(u, (H, W)) * (W / w)]).astype(np.float32)


def bg_subtracted(plane, px_um):
    from scipy import ndimage as ndi
    p = plane.astype(np.float32)
    return np.clip(ndi.gaussian_filter(p, 1.0) - ndi.gaussian_filter(p, 2.8 / (px_um or 0.1)), 0, None)


def _match(pad0, pad1, o, y, x, cy, cx, h, R, prior_sigma=None):
    """NCC search of the (2h+1)² template around (y, x) within ±R of (cy, cx)."""
    from skimage.feature import match_template
    yc, xc = int(round(y)), int(round(x))
    cyi, cxi = int(round(cy)), int(round(cx))
    tpl = pad0[yc + o - h:yc + o + h + 1, xc + o - h:xc + o + h + 1]
    srch = pad1[cyi + o - h - R:cyi + o + h + R + 1, cxi + o - h - R:cxi + o + h + R + 1]
    if tpl.shape != (2 * h + 1,) * 2 or srch.shape != (2 * (h + R) + 1,) * 2 \
            or tpl.std() < 1e-6 or srch.std() < 1e-6:
        return None
    res = match_template(srch, tpl)
    sel = res
    if prior_sigma:
        g = np.arange(-R, R + 1)
        sel = res * np.exp(-(g[:, None] ** 2 + g[None] ** 2) / (2 * prior_sigma ** 2))
    k = np.unravel_index(sel.argmax(), sel.shape)
    sc = float(res[k])
    dy, dx = float(k[0] - R), float(k[1] - R)
    if 0 < k[0] < res.shape[0] - 1 and 0 < k[1] < res.shape[1] - 1:
        a, b, c = res[k[0] - 1, k[1]], res[k], res[k[0] + 1, k[1]]
        dn = a - 2 * b + c
        dy += 0.5 * (a - c) / dn if dn != 0 else 0
        a, b, c = res[k[0], k[1] - 1], res[k], res[k[0], k[1] + 1]
        dn = a - 2 * b + c
        dx += 0.5 * (a - c) / dn if dn != 0 else 0
    return cyi + dy, cxi + dx, sc


def predictions(D, det_stack, prm: TrackSettings, px_um, progress=None):
    """predF (flow), pat (template) and predP (mixed) positions of every detection in the next frame."""
    n = len(D['frame'])
    px = px_um or 0.1
    D['predF_y'] = D['y'] + D['flow_y']
    D['predF_x'] = D['x'] + D['flow_x']
    D['pat_y'], D['pat_x'] = np.zeros(n), np.zeros(n)
    D['pat_w'], D['pat_score'] = np.zeros(n), np.full(n, np.nan)
    if not prm.pattern or det_stack is None:
        D['predP_y'], D['predP_x'] = D['predF_y'].copy(), D['predF_x'].copy()
        return
    h, R = max(3, round(prm.pattern_half_um / px)), max(2, round(prm.pattern_search_um / px))
    h2, R2 = max(2, round(prm.refine_half_um / px)), max(2, round(prm.refine_search_um / px))
    o = max(h + R, h2 + R2) + 2
    get = det_stack if callable(det_stack) else (lambda z: det_stack[z])
    frames = sorted({int(f) for f in D['frame']})
    ry, rx, rs = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    py, pxx, ps = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    pad1 = None
    for n_done, f in enumerate(frames[:-1]):
        if f + 1 not in frames:
            pad1 = None
            continue
        pad0 = pad1 if pad1 is not None else np.pad(get(f - 1), o)
        pad1 = np.pad(get(f), o)
        for i in np.flatnonzero(D['frame'] == f):
            y, x = D['y'][i], D['x'][i]
            cy, cx = D['predF_y'][i], D['predF_x'][i]
            m = _match(pad0, pad1, o, y, x, cy, cx, h, R)
            if m:
                py[i], pxx[i], ps[i] = m
            if prm.refine and not (m and m[2] >= prm.score_hi):
                m2 = _match(pad0, pad1, o, y, x, cy, cx, h2, R2, prior_sigma=R2 / 2)
                if m2:
                    ry[i], rx[i], rs[i] = m2
        if progress:
            progress((n_done + 1) / max(len(frames) - 1, 1), f'패턴 매칭 {n_done + 1}/{len(frames) - 1}')
    w = np.nan_to_num(np.where(ps >= prm.score_hi, 1.0, np.where(ps >= prm.score_lo, 0.5, 0.0)))
    use2 = (w < 1) & (np.nan_to_num(rs) >= prm.refine_min) if prm.refine else np.zeros(n, bool)
    py = np.where(use2, ry, py)
    pxx = np.where(use2, rx, pxx)
    w = np.where(use2, prm.refine_weight, w)
    D['pat_score'] = ps
    D['pat_y'], D['pat_x'], D['pat_w'] = np.nan_to_num(py), np.nan_to_num(pxx), w
    D['predP_y'] = np.where(w > 0, w * D['pat_y'] + (1 - w) * D['predF_y'], D['predF_y'])
    D['predP_x'] = np.where(w > 0, w * D['pat_x'] + (1 - w) * D['predF_x'], D['predF_x'])


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------

def _logdiff(a, b):
    with np.errstate(divide='ignore', invalid='ignore'):
        v = np.abs(np.log(np.clip(a, 1e-9, None)[:, None] / np.clip(b, 1e-9, None)[None]))
    return np.nan_to_num(v, nan=0.0, posinf=0.0)


APPEARANCE = {'area': ('area', 'log'), 'cy5': ('mean', 'log'), 'ht_max': ('ri_max', 'lin'),
              'ht_mean': ('ri_mean', 'lin'), 'ecc': ('ecc', 'lin')}   # ParticleTracker's names


def _featdiff(a, b, kind):
    with np.errstate(divide='ignore', invalid='ignore'):
        v = np.abs(np.log(a / b)) if kind == 'log' else np.abs(a - b)
    return np.nan_to_num(v, nan=0.0, posinf=0.0)


def cost_matrix(D, ia, ib, pred, prm: TrackSettings, s, nb=None, gate=None, app_w=None):
    """Cost (cost units) and distance (px) between detections ia (with their
    predicted positions) and ib; s = px per cost unit.  app_w: learned
    appearance weights, used instead of the intensity / area terms."""
    g = np.broadcast_to(np.asarray(prm.gate_um / UNIT_UM if gate is None else gate, float), (len(ia),))[:, None]
    P = pred
    Q = np.stack([D['y'][ib], D['x'][ib]], 1)
    d = np.linalg.norm(P[:, None] - Q[None], axis=2) / s
    base = prm.gate_um / UNIT_UM
    c = d * (base / g)
    c += prm.w_cell * (D['cell'][ia][:, None] != D['cell'][ib][None])
    if app_w:
        for k, w in app_w.items():
            col, kind = APPEARANCE[k]
            if w > 0 and col in D:
                c += prm.appearance_scale * w * _featdiff(D[col][ia][:, None], D[col][ib][None], kind)
    else:
        c += prm.w_int * _logdiff(D['mean'][ia], D['mean'][ib])
        c += prm.w_area * _logdiff(D['area'][ia], D['area'][ib])
    if nb is not None:
        disp = (Q[None] - np.stack([D['y'][ia], D['x'][ia]], 1)[:, None]) / s
        dev = np.linalg.norm(disp - nb[:, None, :], axis=2)
        ok = ~np.isnan(nb[:, 0])
        c[ok] += prm.w_nb * dev[ok]
    c[d > g] = np.inf
    return c, d


def lap(c, end_cost):
    """One-to-one assignment with termination / start costs."""
    from scipy.optimize import linear_sum_assignment
    na, nb = c.shape
    big = 1e6
    M = np.full((na + nb, nb + na), big)
    M[:na, :nb] = np.where(np.isinf(c), big, c)
    M[:na, nb:] = np.where(np.eye(na) > 0, end_cost, big)
    M[na:, :nb] = np.where(np.eye(nb) > 0, end_cost, big)
    M[na:, nb:] = np.where(M[:na, :nb].T < big, 0, big)
    r, cl = linear_sum_assignment(M)
    return [(i, j) for i, j in zip(r, cl) if i < na and j < nb and M[i, j] < big]


def neighbour_median(D, ia, disp, prm: TrackSettings, px):
    from scipy.spatial import cKDTree
    out = np.full((len(ia), 2), np.nan)
    if not len(ia):
        return out
    xy = np.stack([D['y'][ia], D['x'][ia]], 1)
    tr = cKDTree(xy)
    for i, nbs in enumerate(tr.query_ball_point(xy, prm.nb_radius_um / px)):
        nbs = [j for j in nbs if j != i and ia[j] in disp and D['cell'][ia[j]] == D['cell'][ia[i]]]
        if len(nbs) >= prm.nb_min:
            out[i] = np.median([disp[ia[j]] for j in nbs], 0)
    return out


def learn_appearance(D, links, s):
    """ParticleTracker's appearance weights from the sure first-pass links
    (pattern score ≥ 0.9, cost margin ≥ 2): exponential scales of the change
    along the same particle (s_same) and against the nearest other candidate
    (s_other) per feature, w = (1/s_same − 1/s_other) / w_dist, in cost units."""
    from scipy.spatial import cKDTree
    L = [(a, b, d / UNIT_UM) for a, b, _c, d, m in links
         if np.nan_to_num(D['pat_score'][a]) >= 0.9 and m >= 2]
    if len(L) < 50:
        return {}, {}
    pos = np.stack([D['y'], D['x']], 1) / s
    fr = D['frame']
    trees = {f: (cKDTree(pos[fr == f]), np.flatnonzero(fr == f)) for f in np.unique(fr)}
    feats = {k: v for k, v in APPEARANCE.items() if v[0] in D}
    same = {k: [] for k in feats}
    other = {k: [] for k in feats}
    dsame, dother = [], []
    for a, b, pd_ in L:
        tr, ids = trees[fr[b]]
        if len(ids) < 2:
            continue
        dd, ii = tr.query(pos[b], k=2)
        if not np.isfinite(dd[1]):
            continue
        o = ids[ii[1]]
        dsame.append(pd_)
        dother.append(float(np.linalg.norm(pos[o] - pos[b])) + pd_)
        for k, (col, kind) in feats.items():
            same[k].append(float(_featdiff(np.array([D[col][a]]), np.array([D[col][b]]), kind)[0]))
            other[k].append(float(_featdiff(np.array([D[col][a]]), np.array([D[col][o]]), kind)[0]))

    def sc(x):
        return max(float(np.nanmean(x)), 1e-6) if len(x) else 1e-6
    w_dist = 1 / sc(dsame) - 1 / sc(dother)
    if w_dist <= 0:
        return {}, {}
    W = {k: max(0.0, (1 / sc(same[k]) - 1 / sc(other[k])) / w_dist) for k in feats}
    stats = {k: dict(s_same=sc(same[k]), s_other=sc(other[k]), weight=W[k]) for k in feats}
    stats['n_links'] = len(dsame)
    return W, stats


def link_frames(D, prm: TrackSettings, px_um, progress=None):
    """Frame-to-frame links; with prm.appearance and an RI channel two passes
    as in ParticleTracker: the first pass's sure links teach the appearance
    weights, the second links with them.  Returns links, pred, gate_used, app_w."""
    px = px_um or 0.1
    if not prm.appearance or 'ri_max' not in D:
        return (*_link_frames(D, prm, px_um, progress), None)
    half = (lambda f, m: progress(f * 0.5, '1차 ' + m)) if progress else None
    first = _link_frames(D, prm, px_um, half)
    W, stats = learn_appearance(D, first[0], UNIT_UM / px)
    D['_appearance'] = stats
    if not W:
        return (*first, None)
    half = (lambda f, m: progress(0.5 + f * 0.5, '2차 (외형) ' + m)) if progress else None
    return (*_link_frames(D, prm, px_um, half, app_w=W), W)


def _link_frames(D, prm: TrackSettings, px_um, progress=None, app_w=None):
    """Frame-to-frame links (a, b, cost, distance µm, margin) and the prediction / gate used per detection."""
    px = px_um or 0.1
    s = UNIT_UM / px                           # px per cost unit
    n = len(D['frame'])
    frames = sorted({int(f) for f in D['frame']}) if n else []
    pos = np.stack([D['y'], D['x']], 1) if n else np.zeros((0, 2))
    flow = np.stack([D['flow_y'], D['flow_x']], 1) if n else np.zeros((0, 2))
    base = prm.gate_um / UNIT_UM
    u = np.zeros((n, 2))
    has_u = np.zeros(n, bool)
    rms = np.full(n, base / max(prm.gate_k, 1e-6))
    pred = np.stack([D['predP_y'], D['predP_x']], 1) if n else np.zeros((0, 2))
    gate_used = np.full(n, base)
    links = []
    for k_, t in enumerate(frames[:-1]):
        ia = np.flatnonzero(D['frame'] == t)
        ib = np.flatnonzero(D['frame'] == t + 1)
        if not len(ia) or not len(ib):
            continue
        if prm.velocity:
            pv = np.stack([D['predF_y'][ia], D['predF_x'][ia]], 1) + np.where(has_u[ia, None], u[ia] * s, 0)
            w = D['pat_w'][ia][:, None]
            pat = np.stack([D['pat_y'][ia], D['pat_x'][ia]], 1)
            pred[ia] = np.where(w > 0, w * pat + (1 - w) * pv, pv)
            gate_used[ia] = np.where(has_u[ia], np.clip(prm.gate_k * rms[ia], base, prm.gate_max_um / UNIT_UM), base)
        g = gate_used[ia] if prm.velocity else None
        c, d = cost_matrix(D, ia, ib, pred[ia], prm, s, gate=g, app_w=app_w)
        L1 = lap(c, base + 2)
        dm = {ia[i]: (pos[ib[j]] - pos[ia[i]]) / s for i, j in L1}
        nb = neighbour_median(D, ia, dm, prm, px)
        c, d = cost_matrix(D, ia, ib, pred[ia], prm, s, nb, gate=g, app_w=app_w)
        L1 = lap(c, base + 2)
        srt = np.sort(np.where(np.isfinite(c), c, 1e6), 1)
        for i, j in L1:
            a, b = ia[i], ib[j]
            mg = (srt[i, 1] - c[i, j]) if c.shape[1] > 1 else 1e6
            links.append((a, b, float(c[i, j]), float(d[i, j] * UNIT_UM), float(mg)))
            if prm.velocity:
                uo = (pos[b] - pos[a] - flow[a]) / s
                al = prm.vel_alpha
                u[b] = al * uo + (1 - al) * u[a] if has_u[a] else al * uo
                has_u[b] = True
                rms[b] = math.sqrt(al * d[i, j] ** 2 + (1 - al) * rms[a] ** 2)
        if progress:
            progress((k_ + 1) / max(len(frames) - 1, 1), f'연결 {k_ + 1}/{len(frames) - 1}')
    return links, pred, gate_used


def build_tracks(D, links, pred, gate_used, prm: TrackSettings, px_um, app_w=None):
    """Track id per detection (1-based, 0 = none), gaps closed over up to
    gap_max missing frames (gap_max 1: ParticleTracker's one-frame closing)."""
    from scipy.optimize import linear_sum_assignment
    n = len(D['frame'])
    nxt = {a: b for a, b, *_ in links}
    has_prev = {b for _, b, *_ in links}
    tid = np.full(n, -1)
    k = 0
    for s0 in np.argsort(D['frame'], kind='stable'):
        if s0 in has_prev or tid[s0] >= 0:
            continue
        cur = s0
        while True:
            tid[cur] = k
            if cur in nxt:
                cur = nxt[cur]
            else:
                break
        k += 1
    mp = {}
    if prm.gap_max == 1 and k > 1:
        _close_one_gap(D, tid, pred, gate_used, prm, px_um, app_w, mp)
    elif prm.gap_max > 1 and k > 1:
        _close_gaps_pt(D, tid, pred, gate_used, prm, px_um, app_w, mp)

    def root(x):
        seen = set()
        while x in mp and x not in seen:
            seen.add(x)
            x = mp[x]
        return x
    roots = np.array([root(t) for t in tid])
    order = {}
    for i in np.argsort(D['frame'], kind='stable'):
        order.setdefault(roots[i], len(order) + 1)
    return np.array([order[r] for r in roots], int), len(mp)


def _close_gaps_pt(D, tid, pred, gate_used, prm: TrackSettings, px_um, app_w, mp):
    """ParticleTracker's close_gaps (u-track style, up to gap_max missing
    frames: forward and backward extrapolation, gate × √(gap + 1), appearance
    of the last / first 3 points, one assignment per connected group), run on
    this app's detections in ParticleTracker's units."""
    import pandas as pd

    from .ptcore.config import TrackingParams
    from .ptcore.tracking import close_gaps
    px = px_um or 0.1
    s = UNIT_UM / px
    cols = dict(track_id=np.asarray(tid), frame=D['frame'].astype(int), y_ht=D['y'] / s, x_ht=D['x'] / s,
                pred_y=pred[:, 0] / s, pred_x=pred[:, 1] / s, gate_used=np.asarray(gate_used, float),
                cell_id=D['cell'].astype(int), mean_intensity=D['mean'], area_px=D['area'], eccentricity=D['ecc'])
    if 'ri_max' in D:
        cols['ht_ri_max'], cols['ht_ri_mean'] = D['ri_max'], D['ri_mean']
    tp = TrackingParams()
    tp.gate, tp.gate_max = prm.gate_um / UNIT_UM, max(prm.gate_max_um, prm.gate_um) / UNIT_UM
    tp.gap_max, tp.gap_penalty, tp.w_cell = int(prm.gap_max), prm.gap_penalty, prm.w_cell
    tp.w_int, tp.w_area, tp.appearance_scale = prm.w_int, prm.w_area, prm.appearance_scale
    mp.update({int(k): int(v) for k, v in close_gaps(pd.DataFrame(cols), tp, app_w).items()})


def _close_one_gap(D, tid, pred, gate_used, prm: TrackSettings, px_um, app_w, mp):
    """ParticleTracker's gap closing for one missing frame: a track ending at
    frame t and one starting at t + 2, end extrapolated two steps (2 × pred −
    position), gate × 1.3, the linking cost without the neighbour term, one
    assignment per frame."""
    from scipy.optimize import linear_sum_assignment
    px = px_um or 0.1
    s = UNIT_UM / px
    base = prm.gate_um / UNIT_UM
    first, last = {}, {}
    for i in np.argsort(D['frame'], kind='stable'):
        first.setdefault(tid[i], i)
        last[tid[i]] = i
    ends = np.array(list(last.values()), int)
    starts = np.array(list(first.values()), int)
    fe, fs = D['frame'][ends], D['frame'][starts]
    for t in sorted({int(f) for f in fe}):
        E = ends[fe == t]
        S = starts[fs == t + 2]
        if not len(E) or not len(S):
            continue
        P = 2 * pred[E] - np.stack([D['y'][E], D['x'][E]], 1)
        gg = (gate_used[E] if prm.velocity else np.full(len(E), base)) * 1.3
        c, _ = cost_matrix(D, E, S, P, prm, s, gate=gg, app_w=app_w)
        c = np.where(np.isinf(c), 1e6, c)
        for i, j in zip(*linear_sum_assignment(c)):
            if c[i, j] < 1e6:
                mp[tid[S[j]]] = tid[E[i]]


# ---------------------------------------------------------------------------
# the whole run on detections
# ---------------------------------------------------------------------------

def track(rows, det_stack, prm: TrackSettings, px_um, times_s, progress=None):
    """Detections (rows of frame_detections, with flow_y / flow_x) -> point rows
    (sorted by track and frame) and the number of gaps closed."""
    if not rows:
        return [], 0
    keys = ['frame', 'label', 'y', 'x', 'area', 'mean', 'ecc', 'cell', 'flow_y', 'flow_x']
    if all('ri_max' in r for r in rows):
        keys += ['ri_mean', 'ri_max']
    D = as_columns(rows, keys)
    D['cell'] = D['cell'].astype(int)
    predictions(D, det_stack, prm, px_um, progress)
    links, pred, gate_used, app_w = link_frames(D, prm, px_um, progress)
    tid, n_gap = build_tracks(D, links, pred, gate_used, prm, px_um, app_w)
    track.last_appearance = D.get('_appearance') if app_w else None
    lk = {b: (c, d, m) for a, b, c, d, m in links}
    px = px_um or 0.1
    pts = []
    for i, r in enumerate(rows):
        p = dict(r)
        p['track_id'] = int(tid[i])
        c, d, m = lk.get(i, (float('nan'),) * 3)
        p['link_cost'], p['link_margin'] = c, m
        p['pat_score'] = float(D['pat_score'][i])
        p['gate_um'] = float(gate_used[i] * UNIT_UM)
        p['_predF'] = (float(D['predF_y'][i]), float(D['predF_x'][i]))
        pts.append(p)
    pts.sort(key=lambda p: (p['track_id'], p['frame']))
    prev = None
    for p in pts:
        t = p['frame'] - 1
        p['time_s'] = float(times_s[t]) if t < len(times_s) else float(t)
        p['time_min'] = p['time_s'] / 60
        p['x_px'], p['y_px'] = p['x'], p['y']
        p['x_um'], p['y_um'] = p['x'] * px, p['y'] * px
        p['area_um2'] = p['area'] * px * px
        if prev is not None and prev['track_id'] == p['track_id']:
            p['step_um'] = math.hypot(p['x'] - prev['x'], p['y'] - prev['y']) * px
            p['gap_before'] = int(p['frame'] - prev['frame'] - 1)
            if p['gap_before'] == 0:
                fy, fx = prev['_predF']
                p['cell_carried_um'] = math.hypot(fy - prev['y'], fx - prev['x']) * px
                p['residual_um'] = math.hypot(p['y'] - fy, p['x'] - fx) * px
            else:
                p['cell_carried_um'] = p['residual_um'] = float('nan')
        else:
            p['step_um'] = p['cell_carried_um'] = p['residual_um'] = float('nan')
            p['gap_before'] = 0
        prev = p
    for p in pts:
        p.pop('_predF', None)
    return pts, n_gap


def add_ratio(pts, prm: TrackSettings):
    """ratio_<B>_<A> (and _unfiltered), merged flags."""
    b, a = prm.ratio_b, prm.ratio_a
    name = f'ratio_{b}_{a}' if a and b else ''
    # merged: area and total reference intensity jump together against the track's last 3 points
    ref = f'I_{a}_raw' if a else None
    by = {}
    for p in pts:
        by.setdefault(p['track_id'], []).append(p)
    for tr in by.values():
        tr.sort(key=lambda p: p['frame'])
        area = np.array([p['area'] for p in tr], float)
        integ = area * np.array([p.get(ref, p['mean']) if ref else p['mean'] for p in tr], float)
        raw = np.zeros(len(tr), bool)
        base = np.full(len(tr), np.nan)
        for i in range(1, len(tr)):
            ra = np.median(area[max(0, i - 3):i])
            ri = np.median(integ[max(0, i - 3):i])
            base[i] = ra
            raw[i] = area[i] >= prm.merge_area_ratio * ra and integ[i] >= prm.merge_int_ratio * ri
        m = raw.copy()
        i = 0
        while i < len(tr):
            if raw[i]:
                j, k = i + 1, 1
                while j < len(tr) and k < prm.merge_max_frames and area[j] >= prm.merge_area_ratio * base[i]:
                    m[j] = True
                    j += 1
                    k += 1
                i = j
            else:
                i += 1
        for p, f in zip(tr, m):
            p['merged'] = bool(f)
    if not name:
        return ''
    for p in pts:
        ia, ib = p.get(f'I_{a}', float('nan')), p.get(f'I_{b}', float('nan'))
        v = ib / ia if ia == ia and ib == ib and ia > prm.min_ia else float('nan')
        p[name + '_unfiltered'] = v
        p[name] = float('nan') if (prm.exclude_merged and p.get('merged')) else v
    return name


def summary(pts, channels, prm: TrackSettings, ratio_col=''):
    """One row per track (proposal 4.3)."""
    by = {}
    for p in pts:
        by.setdefault(p['track_id'], []).append(p)
    out = []
    for tid, tr in sorted(by.items()):
        tr.sort(key=lambda p: p['frame'])
        n = len(tr)
        cells = [p['cell'] for p in tr if p['cell'] > 0]
        locs = [p['loc'] for p in tr]
        dur = tr[-1]['time_min'] - tr[0]['time_min']
        path = float(np.nansum([p['step_um'] for p in tr[1:]]))
        net = math.hypot(tr[-1]['x_um'] - tr[0]['x_um'], tr[-1]['y_um'] - tr[0]['y_um'])
        inside = 1 - locs.count('outside') / n
        row = dict(track_id=tid, start_frame=tr[0]['frame'], end_frame=tr[-1]['frame'], n_points=n,
                   gaps=sum(1 for p in tr if p.get('gap_before')), duration_min=dur,
                   main_cell_id=max(set(cells), key=cells.count) if cells else 0,
                   frac_cytosol=locs.count('cytosol') / n, frac_nucleus=locs.count('nucleus') / n,
                   frac_outside=locs.count('outside') / n,
                   **{'class': tr[0]['pt_group'] if tr[0].get('pt_group') else
                      'short' if n < prm.min_track else ('inside' if inside > prm.inside_fraction else 'outside')},
                   path_um=path, net_disp_um=net, straightness=net / path if path > 0 else float('nan'),
                   mean_speed_um_min=path / dur if dur > 0 else float('nan'),
                   mean_area_um2=float(np.mean([p['area_um2'] for p in tr])))
        for c in channels:
            v = [p.get(f'I_{c}', float('nan')) for p in tr]
            row[f'mean_I_{c}'] = float(np.nanmean(v)) if np.isfinite(v).any() else float('nan')
        if ratio_col:
            r = [(p['time_min'], p[ratio_col]) for p in tr if p.get(ratio_col) == p.get(ratio_col)]
            vals = [v for _, v in r]
            row['mean_ratio'] = float(np.mean(vals)) if vals else float('nan')
            row['ratio_first3'] = float(np.mean(vals[:3])) if vals else float('nan')
            row['ratio_last3'] = float(np.mean(vals[-3:])) if vals else float('nan')
            row['ratio_slope_per_h'] = float(np.polyfit([t / 60 for t, _ in r], vals, 1)[0]) \
                if len(r) >= 3 and len({t for t, _ in r}) > 1 else float('nan')
        out.append(row)
    return out


def per_cell(pts, ratio_col=''):
    """Cells × frames: particle count, median ratio."""
    acc = {}
    for p in pts:
        if p['cell'] <= 0:
            continue
        acc.setdefault((p['cell'], p['frame'], p['time_min']), []).append(p)
    out = []
    for (cell, frame, tm), ps in sorted(acc.items()):
        row = dict(cell_id=cell, frame=frame, time_min=tm, n_particles=len(ps))
        if ratio_col:
            v = [p[ratio_col] for p in ps if p.get(ratio_col) == p.get(ratio_col)]
            row['median_ratio'] = float(np.median(v)) if v else float('nan')
        out.append(row)
    return out


POINT_ORDER = ['track_id', 'frame', 'time_s', 'time_min', 'x_px', 'y_px', 'x_um', 'y_um', 'particle_id',
               'cell_id', 'location', 'area_um2', 'area_px', 'eccentricity']
TAIL = ['step_um', 'cell_carried_um', 'residual_um', 'merged', 'gap_before', 'link_cost', 'link_margin',
        'pat_score', 'gate_um', 'edited']


def point_rows(pts, ratio_col=''):
    """Points as the CSV / graph table (proposal 4.2 columns)."""
    out = []
    for p in pts:
        r = {'track_id': p['track_id'], 'frame': p['frame'], 'time_s': p['time_s'], 'time_min': p['time_min'],
             'x_px': p['x'], 'y_px': p['y'], 'x_um': p['x_um'], 'y_um': p['y_um'], 'particle_id': p['label'],
             'cell_id': p['cell'], 'location': p['loc'], 'area_um2': p['area_um2'], 'area_px': p['area'],
             'eccentricity': p['ecc']}
        for k, v in p.items():
            if k.startswith(('I_', 'bg_', 'ratio_')):
                r[k] = v
        for k in TAIL:
            if k in p:
                r[k] = p[k]
        out.append(r)
    return out


def write_csv(path, rows, extra=None) -> int:
    """Rows (dicts) to CSV with the union of their keys (first-seen order)."""
    keys = list(extra or [])
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, keys, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: _fmt(r.get(k)) for k in keys})
    return len(rows)


def _fmt(v):
    if isinstance(v, float):
        return '' if v != v else f'{v:.6g}'
    if isinstance(v, (bool, np.bool_)):
        return 'True' if v else 'False'
    return '' if v is None else v


# ---------------------------------------------------------------------------
# ParticleTracker results
# ---------------------------------------------------------------------------

PT_REQUIRED = {'track_id', 'frame'}
PT_COORDS = (('x_fl', 'y_fl'), ('x_px', 'y_px'), ('x', 'y'), ('x_ht', 'y_ht'))
PT_REGION = {'cytoplasm': 'cytosol', 'spread_membrane': 'outside', 'background': 'outside'}


def read_csv_rows(path) -> list[dict]:
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def is_pt_points(path) -> bool:
    """A ParticleTracker (or this app's) points CSV: track_id, frame and a coordinate pair."""
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            head = next(csv.reader(f))
    except (OSError, StopIteration, UnicodeDecodeError):
        return False
    h = set(head)
    return PT_REQUIRED <= h and any(a in h and b in h for a, b in PT_COORDS)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float('nan')


def from_pt(rows, px_um, ht_scale=None, chan_a='A', chan_b='B', dataset=None):
    """ParticleTracker points rows -> this app's point dicts (proposal ch. 8: x_fl / y_fl
    -> x_px / y_px (x_ht × scale when only HT is given), I_A / I_B -> I_<channel>,
    ratio_BA -> ratio_<B>_<A>, region -> location with the original kept)."""
    px = px_um or 0.1
    out = []
    for r in rows:
        if dataset is not None and r.get('dataset') not in (None, '', dataset):
            continue
        x = y = float('nan')
        for a, b in PT_COORDS:
            if r.get(a) not in (None, '') and r.get(b) not in (None, ''):
                x, y = _num(r[a]), _num(r[b])
                if a == 'x_ht' and ht_scale:
                    x, y = x * ht_scale, y * ht_scale
                break
        region = r.get('region', '')
        loc = r.get('location') or PT_REGION.get(region, 'outside' if region else 'cytosol')
        frame = int(_num(r['frame']))
        tm = _num(r.get('time_min'))
        p = dict(track_id=int(_num(r['track_id'])), frame=frame, x=x, y=y, x_um=x * px, y_um=y * px,
                 label=int(_num(r.get('roi_label') or r.get('particle_id') or 0)),
                 cell=int(_num(r.get('cell_id') or 0)), loc=loc, region_pt=region,
                 area=_num(r.get('area_px')), ecc=_num(r.get('eccentricity')),
                 time_min=tm if tm == tm else float(frame - 1), mean=_num(r.get('I_A_raw') or r.get('mean_intensity')))
        p['time_s'] = p['time_min'] * 60
        p['area_um2'] = p['area'] * px * px if p['area'] == p['area'] else _num(r.get('area_um2'))
        for src, ch in (('A', chan_a), ('B', chan_b)):
            for pre in ('I_', 'bg_'):
                for suf in ('_raw', ''):
                    k = f'{pre}{src}{suf}'
                    if k in r:
                        p[f'{pre}{ch}{suf}'] = _num(r[k])
        for k, v in r.items():
            if k.startswith(('I_', 'bg_', 'ratio_')) and k not in ('I_A', 'I_B', 'I_A_raw', 'I_B_raw', 'bg_A', 'bg_B',
                                                                  'ratio_BA', 'ratio_BA_raw', 'ratio_BA_unfiltered', 'I_B_max'):
                p[k] = _num(v)
        if 'I_B_max' in r:   # brightest measure-channel pixel of the ROI (입자 추적 › 신호 기준)
            p[f'I_{chan_b}_max'] = _num(r['I_B_max'])
        if 'ratio_BA' in r:
            p[f'ratio_{chan_b}_{chan_a}'] = _num(r['ratio_BA'])
            if 'ratio_BA_unfiltered' in r:
                p[f'ratio_{chan_b}_{chan_a}_unfiltered'] = _num(r['ratio_BA_unfiltered'])
        if 'merged' in r:
            p['merged'] = str(r['merged']).strip().lower() in ('true', '1')
        for k in ('step_um', 'link_cost', 'link_margin', 'pat_score'):
            if k in r:
                p[k] = _num(r[k])
        out.append(p)
    out.sort(key=lambda p: (p['track_id'], p['frame']))
    prev = None
    for p in out:
        if 'step_um' not in p:
            p['step_um'] = math.hypot(p['x_um'] - prev['x_um'], p['y_um'] - prev['y_um']) \
                if prev is not None and prev['track_id'] == p['track_id'] else float('nan')
        p['gap_before'] = int(p['frame'] - prev['frame'] - 1) if prev is not None and prev['track_id'] == p['track_id'] else 0
        p.setdefault('cell_carried_um', float('nan'))
        p.setdefault('residual_um', float('nan'))
        prev = p
    return out


def from_app_rows(rows):
    """This app's own points CSV back to point dicts (project round trip)."""
    out = []
    for r in rows:
        p = {k: _num(v) for k, v in r.items() if k not in ('location',)}
        p['track_id'] = int(p['track_id'])
        p['frame'] = int(p['frame'])
        p['x'], p['y'] = p.pop('x_px'), p.pop('y_px')
        p['label'] = int(p.pop('particle_id', 0) or 0)
        p['cell'] = int(p.pop('cell_id', 0) or 0)
        p['loc'] = r.get('location', 'cytosol')
        p['area'] = p.pop('area_px', float('nan'))
        p['ecc'] = p.pop('eccentricity', float('nan'))
        if 'merged' in r:
            p['merged'] = str(r['merged']).strip().lower() in ('true', '1')
        if 'edited' in r:
            p['edited'] = str(r['edited']).strip().lower() in ('true', '1')
        p['mean'] = p.get('mean', float('nan'))
        out.append(p)
    return out


@dataclass
class TrackState:
    """Tracks of one image (``ImageItem.tracks``)."""

    points: list = field(default_factory=list)       # point dicts (see track())
    outlines: dict = field(default_factory=dict)     # (frame, label) -> outline loops
    settings: dict = field(default_factory=dict)     # TrackSettings.to_dict() used
    key: object = None                               # what the run depended on
    source: str = 'app'                              # 'app' or 'ParticleTracker'
    channels: list = field(default_factory=list)
    ratio: str = ''
    n_gap: int = 0
    edits: list = field(default_factory=list)        # (track_id, frame, action) of 경로 교정

    def tracks(self) -> dict:
        by = {}
        for p in self.points:
            by.setdefault(p['track_id'], []).append(p)
        return by
