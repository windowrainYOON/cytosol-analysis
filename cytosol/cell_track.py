"""세포질 강도 추적 (owner request 2026-11-19/20, mockups v073b–e; built in
v0.73): cells found on every frame, linked into cell tracks, and each cell's
brightness and its change over time measured; condition filters pick the
cells that show the wanted change (for example a rise in 2–6 h that is lost
again by 7–9.5 h) to compare them with all cells.

Pure code (no Qt) so the panel, the batch and the self-test share it:

- `CellTrackSettings`: every setting of the tab (saved in projects).
- `detect_frames`: cell (+ nucleus) labels per frame with the chosen
  algorithm: ParticleTracker's RI cell segmentation (``ptcore.cells``,
  unchanged), the 세포질 ROI algorithm on a cell + nucleus channel, or the
  cells of a ParticleTracker-method 입자 추적 run.
- `link`: one ID per cell across frames: overlap with the previous frame's
  cell moved by the optical flow, frames missed up to ``gap``, divisions
  (a cell that becomes two) flagged.
- `measure_frame`: mean of the region (cytosol = cell − nucleus, or the whole
  cell) in the measure and reference channels, the cell's own background
  ring (``ring_in``–``ring_out`` µm outside its edge, other cells left out),
  the value with every pixel at or below the image's early threshold set to
  0, and the ratio.
- `classify`: classes per cell track (filters by name, 나머지, 제외, 짧은
  세포) over all images at once (상위 % is of all cells).
"""

from __future__ import annotations

import io
from dataclasses import asdict, dataclass, field

import numpy as np
from scipy import ndimage as ndi
from skimage import measure

ALGORITHMS = (('pt', 'ParticleTracker와 같게 (RI 세포 분할)'), ('roi', '세포질 ROI 알고리즘'),
              ('particle', '입자 추적 결과의 세포'))
DIV_MODES = (('both', '둘 다 (RI 상승 · 수축 또는 둘로 나뉨)'), ('ri', 'RI 상승 · 수축 (ParticleTracker)'),
             ('split', '둘로 나뉨'))
EDGE_MODES = (('any', '한 프레임이라도 닿으면'), ('half', '절반 넘는 프레임에서 닿으면'))
VALUES = (('thr', '측정 채널 (기준 이하 = 0)'), ('bg', '측정 채널 (배경 뺀 값)'), ('raw', '측정 채널 (그대로)'),
          ('ratio', '비율 (측정 / 기준 채널)'), ('ref', '기준 채널 (배경 뺀 값)'))
VALUE_COL = {'thr': 'I_thr', 'bg': 'I', 'raw': 'I_raw', 'ratio': 'ratio', 'ref': 'R'}
CHANGES = (('risefall', '증가했다가 감소'), ('rise', '증가'), ('fall', '감소'), ('above', '평균이 값 이상'))
COMBINE = (('all', '모두 만족 (그리고)'), ('any', '하나라도 만족 (또는)'))
CLASS_TEXT = {'rest': '나머지', 'excluded': '제외', 'short': '짧은 세포'}


def default_condition() -> dict:
    return dict(t0=2.0, t1=6.0, value='thr', change='risefall', inc_mode='top', inc=25.0,
                f0=7.0, f1=9.5, fall=60.0)


def default_filter(n=1) -> dict:
    return dict(name=f'필터 {n}', combine='all', conditions=[default_condition()])


@dataclass
class CellTrackSettings:
    algorithm: str = 'pt'            # pt / roi / particle
    cell_channel: str = ''           # channel name ('' = the 세포질 ROI tab's cell channel)
    nuc_channel: str = ''            # roi algorithm: nucleus channel name ('' = none)
    z_project: str = 'mip'           # Z stacks: 'mip' / 'mean' / '' (viewer Z)
    frame0: int = 1
    frame1: int = 0                  # 0 = last
    flow: bool = True                # predict the position by the cells' optical flow
    overlap: float = 0.3             # same cell: overlap of the predicted cell
    gap: int = 2                     # frames a cell may be missed
    min_frames: int = 20             # long cell
    exclude_div: bool = True
    div_mode: str = 'both'
    exclude_edge: bool = True
    edge_mode: str = 'any'
    edge_px: int = 3
    region: str = 'cytosol'          # cytosol (cell − nucleus) / cell
    measure_channel: str = ''
    ref_channel: str = ''            # '' = none
    ring_in: float = 2.0             # µm outside the cell edge
    ring_out: float = 6.0
    base_h: float = 1.0              # change baseline: frames up to this time
    thr_on: bool = True              # pixels at or below the early threshold = 0
    thr_until_min: float = 100.0
    thr_pct: float = 95.0
    filters: list = field(default_factory=lambda: [default_filter()])

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> 'CellTrackSettings':
        s = cls()
        for k, v in (d or {}).items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s


@dataclass
class CellTrackState:
    """Cell tracks of one image (``ImageItem.cell_tracks``)."""

    settings: dict = field(default_factory=dict)
    frames: list = field(default_factory=list)       # timepoints (0-based) measured
    times_h: list = field(default_factory=list)
    labels: bytes = b''                              # npz: linked cell labels (F, H, W)
    rows: list = field(default_factory=list)         # cell × frame dicts
    divided: list = field(default_factory=list)      # cell IDs that divided
    threshold: float = float('nan')                  # measure channel early threshold
    detector: str = ''
    _lab_cache: object = None

    def label_stack(self) -> np.ndarray | None:
        if self._lab_cache is None and self.labels:
            self._lab_cache = np.load(io.BytesIO(self.labels))['L']
        return self._lab_cache

    def labels_at(self, t) -> np.ndarray | None:
        L = self.label_stack()
        if L is None or t not in self.frames:
            return None
        return L[self.frames.index(t)]

    def cells(self) -> dict:
        by = {}
        for r in self.rows:
            by.setdefault(r['cell_id'], []).append(r)
        return by

    def __getstate__(self):
        d = dict(self.__dict__)
        d['_lab_cache'] = None
        return d


def pack_labels(labs) -> bytes:
    b = io.BytesIO()
    L = np.stack(labs)
    np.savez_compressed(b, L=L.astype(np.uint16 if L.max() < 65535 else np.int32))
    return b.getvalue()


# ---------------------------------------------------------------------------
# detection
# ---------------------------------------------------------------------------

def pt_cell_labels(ht_stack, px_um, flow=True, progress=None):
    """ParticleTracker's RI cell segmentation (``ptcore.cells``) frame by frame,
    without its own ID linking (done by `link`); flow of the body images."""
    from .ptcore import cells as ptc
    from .ptcore.config import CellParams
    from .tracking import UNIT_UM
    cp = CellParams()
    f = UNIT_UM / (px_um or UNIT_UM)
    cp.open_radius = max(1, int(round(cp.open_radius * f)))
    cp.smooth_sigma = cp.smooth_sigma * f
    cp.min_cell_area = int(round(cp.min_cell_area * f * f))
    cim = ptc.cell_body_images(np.asarray(ht_stack, np.float32), cp)
    low, core = ptc.cell_thresholds(cim[::4])
    labs = []
    for k in range(len(cim)):
        labs.append(ptc.segment_frame(cim[k], low, core, cp).astype(np.int32))
        if progress:
            progress(f'세포 분할 {k + 1}/{len(cim)}')
    flows = None
    if flow and len(cim) > 1:
        flows = ptc.cell_flow(cim, cp, (lambda _f, m: progress(m)) if progress else None)
    return labs, flows


def pt_native(pt, measure, ref=''):
    """The cells of a ParticleTracker-method 입자 추적 run on ParticleTracker's
    own fluorescence grid, as the 2026-11-19 세포 단위 밝기 analysis measured
    them (scripts/cell_local_bg.py, cell_green_thr.py): cell IDs = its cell
    labels (CID, already linked), sampled at each fluorescence pixel's place on
    the HT grid after that frame's registration; channels as it reads them
    (MIP, measure channel aligned to the reference). ``measure`` / ``ref`` are
    channel names ('CH0 ex474/em515' or 'CH0'). Returns (labels per frame,
    measure stack, reference stack or None, fluorescence pixel µm) or None
    when the channels are not the run's reference / measure channels."""
    from . import pt_engine
    from .ptcore import registration
    from .ptcore.io_utils import split_source
    path, ref_ch = split_source(pt['sources']['reference'])
    mea_ch = split_source(pt['sources']['measure'])[1]
    want = {pt_engine.tcf_channel(measure), pt_engine.tcf_channel(ref) if ref else mea_ch}
    if not want <= {ref_ch, mea_ch}:
        return None
    arr = pt_engine._unpack(pt['arrays'])
    CID, reg, S = arr['CID'], pt['reg'], float(pt['S'])
    A, B, _HT = pt_engine.load(path, ref_ch, mea_ch, pt.get('zmode') or 'mip')
    if pt.get('frames') is not None:
        A, B = A[pt['frames']], B[pt['frames']]
    Bal = registration.align_b(B, reg)
    del B
    stacks = {ref_ch: A, mea_ch: Bal}
    T, NF, NW = A.shape
    NH, NHW = CID.shape[1:]
    yy, xx = np.arange(NF), np.arange(NW)
    labs = []
    for z in range(min(T, len(CID))):
        hy = np.clip(np.round((yy + .5) * S - .5 + reg.dy_ht.values[z]).astype(int), 0, NH - 1)
        hx = np.clip(np.round((xx + .5) * S - .5 + reg.dx_ht.values[z]).astype(int), 0, NHW - 1)
        labs.append(np.asarray(CID[z][np.ix_(hy, hx)], np.int32))
    px = fl_pixel_um(path)
    meas = stacks[pt_engine.tcf_channel(measure)]
    rs = stacks[pt_engine.tcf_channel(ref)] if ref else None
    return labs, meas, rs, px


def fl_pixel_um(path) -> float:
    """Fluorescence pixel size of a TCF (3DFL / 2DFLMIP ResolutionX)."""
    import h5py
    with h5py.File(str(path), 'r') as f:
        for g in ('Data/3DFL', 'Data/2DFLMIP'):
            if g in f and 'ResolutionX' in f[g].attrs:
                return float(np.asarray(f[g].attrs['ResolutionX']).ravel()[0])
    return 0.1125


def image_flows(stack, progress=None):
    """Optical flow between consecutive frames of a cell image (T-1, 2, H, W)."""
    from .tracking import cell_flow
    out = []
    for k in range(len(stack) - 1):
        out.append(cell_flow(np.asarray(stack[k], np.float32), np.asarray(stack[k + 1], np.float32)))
        if progress:
            progress(f'세포 흐름 {k + 1}/{len(stack) - 1}')
    return np.stack(out) if out else None


def warp_labels(lab, flow):
    """Labels of the previous frame moved by the flow (prev → cur)."""
    if flow is None:
        return lab
    H, W = lab.shape
    yy, xx = np.mgrid[0:H, 0:W]
    ys = np.clip(np.round(yy - flow[0]).astype(int), 0, H - 1)
    xs = np.clip(np.round(xx - flow[1]).astype(int), 0, W - 1)
    return lab[ys, xs]


# ---------------------------------------------------------------------------
# linking
# ---------------------------------------------------------------------------

def link(labs, overlap=0.3, gap=2, flows=None):
    """Cell labels per frame → (linked labels, divided IDs).

    A cell takes the ID of the cell it overlaps most (at least ``overlap`` of
    its area) in the previous frame moved by the flow; cells not found there
    are looked for in up to ``gap`` earlier frames (an ID that was missed);
    when one cell becomes two, both new cells are flagged as divided (the
    larger keeps the ID)."""
    out, divided, nxt = [], set(), 1
    last_seen = {}                       # id -> frame index
    for k, lab in enumerate(labs):
        lab = np.asarray(lab)
        cur = np.zeros(lab.shape, np.int32)
        regions = measure.regionprops(lab)
        assigned = {}
        for back in range(1, gap + 2):
            j = k - back
            if j < 0:
                break
            prev = out[j]
            if back == 1 and flows is not None and j < len(flows):
                prev = warp_labels(prev, flows[j])
            pairs = []
            for r in regions:
                if r.label in assigned:
                    continue
                m = lab[r.slice] == r.label
                ov = prev[r.slice][m]
                ov = ov[ov > 0]
                if not ov.size:
                    continue
                v, cn = np.unique(ov, return_counts=True)
                for i, c in zip(v, cn):
                    i = int(i)
                    if back > 1 and last_seen.get(i, -1) != j:
                        continue                 # only IDs missed since frame j
                    if c > overlap * r.area:
                        pairs.append((int(c), r.label, i))
            used = set(assigned.values())
            pairs.sort(reverse=True)
            split_of = {}
            for c, rl, i in pairs:
                if rl in assigned:
                    continue
                if i in used:
                    split_of.setdefault(i, []).append(rl)
                    continue
                assigned[rl] = i
                used.add(i)
            if back == 1:
                for i, rls in split_of.items():   # a second cell on the same parent: division
                    divided.add(i)
                    for rl in rls:
                        if rl not in assigned:
                            assigned[rl] = nxt
                            divided.add(nxt)
                            nxt += 1
        for r in regions:
            i = assigned.get(r.label)
            if i is None:
                i = nxt
                nxt += 1
            nxt = max(nxt, i + 1)
            cur[r.slice][lab[r.slice] == r.label] = i
            last_seen[i] = k
        out.append(cur)
    return out, divided


def ri_mitotic(ht_stack, labs) -> set:
    """Cells ParticleTracker calls mitotic (RI rise with shrinking, or bright
    and round; ``ptcore.cells.mitosis_table`` on RI × 10⁴)."""
    from .ptcore.cells import mitosis_table
    from .ptcore.config import MitosisParams
    HT = np.asarray(ht_stack, np.float32)
    if np.nanmedian(HT[:, ::8, ::8]) < 100:
        HT = HT * 1e4
    CS = mitosis_table(HT, np.stack(labs).astype(np.int32), MitosisParams())
    return set(int(c) for c in CS[CS.mitotic].cell_id)


# ---------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------

def early_threshold(planes_by_frame, times_h, until_min, pct, step=2) -> float:
    """The given percentile of the measure channel's pixels in the frames up
    to ``until_min`` minutes (at least the first frame); every ``step``-th
    pixel (1 = all, as the ParticleTracker-grid measurement)."""
    sel = [p for p, t in zip(planes_by_frame, times_h) if t * 60 <= until_min + 1e-9] or planes_by_frame[:1]
    v = np.concatenate([np.asarray(p, np.float32)[::step, ::step].ravel() for p in sel])
    return float(np.percentile(v, pct)) if v.size else float('nan')


def measure_frame(lab, nuc, meas, ref, px_um, s: CellTrackSettings, thr=float('nan'), edge_px=3,
                  min_ring=20, drop_small_ring=False):
    """Rows of one frame: per linked cell ID the region means, own ring
    background, early-threshold value, ratio, area and edge contact."""
    H, W = lab.shape
    rin, rout = s.ring_in / px_um, s.ring_out / px_um
    free = lab == 0
    rows = []
    objs = ndi.find_objects(lab)
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        pad = int(rout) + 2
        y0, y1 = max(sl[0].start - pad, 0), min(sl[0].stop + pad, H)
        x0, x1 = max(sl[1].start - pad, 0), min(sl[1].stop + pad, W)
        cell = lab[y0:y1, x0:x1] == i
        reg = cell
        if s.region == 'cytosol' and nuc is not None:
            reg = cell & ~(nuc[y0:y1, x0:x1] > 0)
            if reg.sum() < 4:
                reg = cell
        d = ndi.distance_transform_edt(~cell)
        ring = (d > rin) & (d <= rout) & free[y0:y1, x0:x1]
        if drop_small_ring and ring.sum() < min_ring:
            continue                     # no background of its own (ParticleTracker-grid cells)
        ys, xs = np.nonzero(cell)
        r = dict(cell_id=int(i), area_um2=float(cell.sum() * px_um * px_um), x=float(xs.mean() + x0),
                 y=float(ys.mean() + y0),
                 edge=bool(sl[0].start < edge_px or sl[1].start < edge_px or sl[0].stop > H - edge_px or
                           sl[1].stop > W - edge_px), ring_px=int(ring.sum()))
        m = meas[y0:y1, x0:x1].astype(float)
        r['I_raw'] = float(m[reg].mean())
        r['bg'] = float(m[ring].mean()) if ring.sum() >= min_ring else float('nan')
        r['I'] = r['I_raw'] - r['bg'] if np.isfinite(r['bg']) else float('nan')
        if np.isfinite(thr):
            r['I_thr'] = float(np.where(m[reg] > thr, m[reg], 0.0).mean())
            r['pos_frac'] = float((m[reg] > thr).mean())
        else:
            r['I_thr'] = r['pos_frac'] = float('nan')
        if ref is not None:
            a = ref[y0:y1, x0:x1].astype(float)
            r['R_raw'] = float(a[reg].mean())
            r['R_bg'] = float(a[ring].mean()) if ring.sum() >= min_ring else float('nan')
            r['R'] = r['R_raw'] - r['R_bg'] if np.isfinite(r['R_bg']) else float('nan')
            num = r['I_thr'] if s.thr_on and np.isfinite(r['I_thr']) else r['I']
            r['ratio'] = num / r['R'] if np.isfinite(r['R']) and r['R'] > 0 else float('nan')
        rows.append(r)
    return rows


def add_changes(rows, base_h):
    """I_change / I_thr_change / ratio_change: value − the cell's mean over
    the frames up to ``base_h`` hours (its first frame when none)."""
    by = {}
    for r in rows:
        by.setdefault(r['cell_id'], []).append(r)
    for rs in by.values():
        rs.sort(key=lambda r: r['frame'])
        for col in ('I', 'I_thr', 'ratio'):
            if col not in rs[0]:
                continue
            early = [r[col] for r in rs if r['time_h'] <= base_h + 1e-9 and np.isfinite(r[col])]
            if not early:
                early = [next((r[col] for r in rs if np.isfinite(r[col])), float('nan'))]
            b = float(np.mean(early))
            for r in rs:
                r[f'{col}_change'] = r[col] - b if np.isfinite(r[col]) else float('nan')
    return rows


# ---------------------------------------------------------------------------
# classes
# ---------------------------------------------------------------------------

def _series(rs, value):
    col = VALUE_COL.get(value, 'I')
    t = np.array([r['time_h'] for r in rs], float)
    v = np.array([r.get(col, np.nan) for r in rs], float)
    ok = np.isfinite(v)
    return t[ok], v[ok]


def _cond_numbers(rs, c, base_h):
    """(rise, drop, fall_ok, mean) of one cell for one condition."""
    t, v = _series(rs, c.get('value', 'thr'))
    if not len(v):
        return None
    early = v[t <= base_h + 1e-9]
    base = float(early.mean()) if len(early) else float(v[0])
    w = v[(t >= c['t0'] - 1e-9) & (t <= c['t1'] + 1e-9)]
    if not len(w):
        return None
    peak = float(w.max())
    rise = peak - base
    drop = base - float(w.min())
    fw = v[(t >= c.get('f0', 0) - 1e-9) & (t <= c.get('f1', 0) + 1e-9)]
    fall_ok = bool(len(fw)) and rise > 0 and float(fw.min()) <= peak - c.get('fall', 60.0) / 100 * rise
    return rise, drop, fall_ok, float(w.mean())


def classify(cells, s: CellTrackSettings):
    """cells: [(key, rows of one cell, flags dict(divided, edge_frac))] of every
    image → {key: class}. 상위 % thresholds are over all long, kept cells."""
    out, cand = {}, []
    for key, rs, fl in cells:
        if len(rs) < s.min_frames:
            out[key] = 'short'
            continue
        edge = fl.get('edge_frac', 0.0)
        edge_bad = edge > 0 if s.edge_mode == 'any' else edge > 0.5
        if (s.exclude_div and fl.get('divided')) or (s.exclude_edge and edge_bad):
            out[key] = 'excluded'
            continue
        cand.append((key, rs))
    for f in s.filters or []:
        conds = f.get('conditions') or []
        nums = {}
        for ci, c in enumerate(conds):
            nums[ci] = {key: _cond_numbers(rs, c, s.base_h) for key, rs in cand}
        cut = {}
        for ci, c in enumerate(conds):
            if c.get('inc_mode') == 'top':
                col = 1 if c.get('change') == 'fall' else 0
                vals = [n[col] for n in nums[ci].values() if n is not None]
                cut[ci] = float(np.percentile(vals, 100 - c.get('inc', 25.0))) if vals else np.inf
            else:
                cut[ci] = float(c.get('inc', 0.0))
        for key, _rs in cand:
            if key in out:
                continue
            res = []
            for ci, c in enumerate(conds):
                n = nums[ci][key]
                if n is None:
                    res.append(False)
                    continue
                rise, drop, fall_ok, mean = n
                ch = c.get('change', 'risefall')
                if ch == 'rise':
                    ok = rise > 0 and rise >= cut[ci]
                elif ch == 'fall':
                    ok = drop > 0 and drop >= cut[ci]
                elif ch == 'above':
                    ok = mean >= cut[ci]
                else:
                    ok = rise > 0 and rise >= cut[ci] and fall_ok
                res.append(ok)
            hit = (all(res) if f.get('combine', 'all') == 'all' else any(res)) if res else False
            if hit:
                out[key] = f.get('name') or '필터'
    for key, _rs in cand:
        out.setdefault(key, 'rest')
    return out


def class_text(k) -> str:
    return CLASS_TEXT.get(k, k)
