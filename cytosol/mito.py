"""mitoROI (v0.67, owner request 2026-11-13/14, design doc mito-tracking ch. 1–5):
Mito Analyzer 1.8.0's measurements on this app's cell ROIs.

Per image: the mitochondria channel is split into mito objects inside every
cell (``split``: rolling ball 1.5 µm + adaptive threshold AND 0.5 × Otsu,
h-maxima watershed; ``otsu``: MiNA's Otsu per cell; or a manual threshold
of the preprocessed image), skeletonised and measured as MiNA does; the
protein-of-interest channel (optional) gives green on / off mito, puncta
(top-hat, one threshold per image), Pearson / Manders and green+ / green−
cells. The code in ``cytosol.mitoan`` is Mito Analyzer's own, so the
numbers equal its ``_per_cell`` / ``_per_mito`` / ``_green_puncta`` CSVs
for the same ROIs."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field, fields

import numpy as np

from .mitoan import REF_PX_UM, normalize_green

METHODS = (('split', '조각 분할 (적응 임계값 + 접촉선 분리)'), ('otsu', 'MiNA 기본 (세포마다 Otsu)'))


@dataclass
class MitoSettings:
    mito_channel: str = ''
    poi_channel: str = ''              # '' = none
    include_edge_cells: bool = False
    exclude_weak: bool = False         # drop cells whose border with a neighbour is weak (binucleate QC)
    binuc_tau: float = 0.0
    mito_method: str = 'split'
    thr_mito: float = 0.0              # 0 = automatic
    min_mito_area_um2: float = 0.05
    green_bg: float = 0.0              # 0 = automatic (dark-gap level of the smoothed green)
    green_pos_percent: float = 2.0
    puncta_sensitivity: float = 1.0
    thr_puncta: float = 0.0            # 0 = automatic
    thr_green_bright: float = 0.0      # 0 = automatic

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (d or {}).items() if k in names})


@dataclass
class MitoResult:
    settings: dict = field(default_factory=dict)
    cells: list = field(default_factory=list)       # per cell rows (Mito Analyzer _per_cell columns)
    mito: list = field(default_factory=list)        # per mito object rows
    puncta: list = field(default_factory=list)      # per punctum rows
    used: dict = field(default_factory=dict)        # thresholds and levels actually used
    layers: dict = field(default_factory=dict)      # name -> bool image (mito, skeleton, ends, junctions, puncta)
    mlab: object = None                             # mito object labels
    source: str = 'app'                             # or 'Mito Analyzer'

    def status_counts(self):
        c = {}
        for r in self.cells:
            c[r.get('green_status', '')] = c.get(r.get('green_status', ''), 0) + 1
        return c


def _border_status(lab, margin=3):
    h, w = lab.shape
    edge = set(np.unique(np.r_[lab[:margin].ravel(), lab[-margin:].ravel(),
                               lab[:, :margin].ravel(), lab[:, -margin:].ravel()]).tolist()) - {0}
    return edge


def _weak_partners(lab, dens, tau, min_border=30):
    """Mito Analyzer cell_roi.qc_status partners: neighbours whose shared
    border is not darker than tau × the dimmer cell's median density."""
    from skimage import segmentation  # noqa: F401
    n = int(lab.max())
    med = {l: float(np.median(dens[lab == l])) for l in range(1, n + 1) if (lab == l).any()}
    partners = {l: [] for l in med}
    if tau <= 0:
        return partners
    pairs = {}
    for a, b in ((lab[:, :-1], lab[:, 1:]), (lab[:-1], lab[1:])):
        m = (a != b) & (a > 0) & (b > 0)
        da = dens[:, :-1][m] if a.shape[1] != lab.shape[1] else dens[:-1][m]
        for p, q, d in zip(a[m], b[m], da):
            key = (min(p, q), max(p, q))
            s = pairs.setdefault(key, [0.0, 0])
            s[0] += d
            s[1] += 1
    for (p, q), (tot, nb) in pairs.items():
        if nb < min_border or p not in med or q not in med:
            continue
        m = min(med[p], med[q])
        if m > 0 and (m - tot / nb) / m < tau:
            partners[p].append(q)
            partners[q].append(p)
    return partners


def analyze(planes, channels, cells, px_um, s: MitoSettings, log=None) -> MitoResult:
    """Mito Analyzer's steps 3–5 on (C, Y, X) planes and a CellRois."""
    from scipy import ndimage as ndi

    from .mitoan import green as green_q
    from .mitoan import green_cells, mina, mito_objects

    log = log or (lambda m: None)
    if s.mito_channel not in channels:
        raise ValueError('미토콘드리아 채널을 고르세요.')
    red = np.asarray(planes[channels.index(s.mito_channel)], float)
    green = np.asarray(planes[channels.index(s.poi_channel)], float) if s.poi_channel in channels else None
    px = float(px_um or REF_PX_UM)
    k = float(np.clip(REF_PX_UM / px, 0.2, 5))
    lab = np.asarray(cells.labels, np.int32)
    nuc = cells.nuclei if getattr(cells, 'nuclei', None) is not None else np.zeros_like(lab)
    used = dict(pixel_um=px, k=k)
    gn = norm = None
    if green is not None:
        gn, norm = normalize_green(green, k)
        if s.green_bg > 0:
            norm = dict(norm, offset=float(s.green_bg))
        used['green_background'] = norm['offset']
        used['green_background_auto'] = s.green_bg <= 0
    # QC: edge cells, weak-border neighbours (as cell_roi.save_outputs)
    edge = _border_status(lab)
    dens_src = gn if gn is not None else red / max(np.percentile(red, 75), 1e-9) * 4.79
    dens = ndi.gaussian_filter(np.log1p(np.clip(dens_src, 0, 20)), 10 * k)
    partners = _weak_partners(lab, dens, s.binuc_tau) if s.exclude_weak else {}
    rois = []
    for l in range(1, int(lab.max()) + 1):
        if not (lab == l).any():
            continue
        st = 'edge' if l in edge else ('binucleate' if partners.get(l) else 'ok')
        rois.append(dict(roi=f'cell{l:02d}', status=st, touches_border=l in edge,
                         weak_border_with=';'.join(f'cell{q:02d}' for q in partners.get(l, []))))
    analysed = [int(r['roi'][4:]) for r in rois if r['status'] == 'ok' or (s.include_edge_cells and r['status'] == 'edge')]
    mask_fn = None
    if s.mito_method == 'split':
        p0 = dict(mito_objects.P, sigma=mito_objects.P['sigma'] * k, manual_thr=s.thr_mito)
        sm = mito_objects.preprocess(red, px, p0)
        q = mito_objects.scaled_params(sm, np.isin(lab, analysed), k, p0)

        def mask_fn(cell):
            fg, _, sep = mito_objects.segment_cell(sm, cell, px, q)
            return sep > 0, mito_objects.fragmentation_metrics(fg, sep, cell, px)
    elif s.thr_mito > 0:
        sm = mito_objects.preprocess(red, px, dict(mito_objects.P, sigma=mito_objects.P['sigma'] * k))

        def mask_fn(cell):
            return cell & (sm > s.thr_mito), {}
    rows, b, sk, end, junc = mina.analyze_cells(red, lab, [r for r in rois if int(r['roi'][4:]) in analysed], px,
                                                green, True, log=log, mask_fn=mask_fn)
    used['mito_threshold'] = s.thr_mito if s.thr_mito > 0 else 'auto'
    if s.mito_method == 'otsu' and s.thr_mito <= 0:
        t = [r['otsu_threshold'] for r in rows if np.isfinite(r['otsu_threshold'])]
        used['mito_threshold_range'] = (min(t), max(t)) if t else None
    mito_rows, puncta_rows, mlab, plab = [], [], None, np.zeros(lab.shape, int)
    if green is not None and rows:
        mito_rows, puncta_rows, mlab, plab, thr = green_q.quantify(
            green, red, lab, b, rows, px, bg=norm['offset'], k=k, sensitivity=s.puncta_sensitivity,
            min_mito_area_um2=s.min_mito_area_um2, log=log, puncta_thr=s.thr_puncta)
        used['puncta_threshold'] = thr
        used['puncta_threshold_auto'] = s.thr_puncta <= 0
        gstatus, ginfo = green_cells.classify(gn, lab, nuc, k, s.green_pos_percent / 100, s.thr_green_bright)
        used['green_bright_threshold'] = ginfo['threshold']
        for row in rows:
            c = int(row['cell'][4:])
            row['green_status'] = gstatus.get(c, '')
            row['green_bright_area_percent'] = 100 * ginfo['fraction'].get(c, 0.0)
        cstat = {row['cell']: row['green_status'] for row in rows}
        for t_ in (mito_rows, puncta_rows):
            for row in t_:
                row['green_status'] = cstat.get(row['cell'], '')
    else:
        # mito objects without a POI channel: connected pieces of the mask per cell
        from skimage import measure, morphology
        mlab = np.zeros(lab.shape, int)
        nxt = 0
        min_px = max(1, round(s.min_mito_area_um2 / (px * px)))
        for row in rows:
            cid = int(row['cell'][4:])
            l = measure.label(morphology.remove_small_objects(b & (lab == cid), max_size=min_px - 1, connectivity=2),
                              connectivity=2)
            mlab[l > 0] = l[l > 0] + nxt
            nxt += l.max()
        for mr in measure.regionprops(mlab, intensity_image=red):
            obj = mr.image
            cid = int(lab[mr.slice][obj][0])
            edges, ng, br, summed, donuts, e_, j_ = mina.analyze_skeleton(
                np.pad(morphology.skeletonize(obj, method='lee').astype(bool), 1), px)
            major, minor = max(mr.axis_major_length, 1.0), max(mr.axis_minor_length, 1.0)
            mito_rows.append(dict(
                mito=f'm{mr.label:04d}', cell=f'cell{cid:02d}', area_um2=mr.area * px * px,
                length_um=float(sum(e[3] for e in edges)), n_branches=len(edges),
                n_junctions=int(ndi.label(j_, structure=np.ones((3, 3)))[1]), n_endpoints=int(e_.sum()),
                donut=bool(donuts), major_axis_um=major * px, minor_axis_um=minor * px, aspect_ratio=major / minor,
                solidity=mr.solidity, form_factor=(mr.perimeter * px) ** 2 / (4 * np.pi * mr.area * px * px),
                red_mean=float(mr.intensity_mean), centroid_x=mr.centroid[1], centroid_y=mr.centroid[0]))
    by = {r['roi']: r for r in rois}
    cents = {}
    from skimage import measure
    for rp in measure.regionprops(lab):
        cents[rp.label] = rp.centroid
    out = []
    for row in rows:
        c = int(row['cell'][4:])
        d = {'cell': row['cell'], 'green_status': row.get('green_status', ''), **row}
        d['centroid_x'] = round(cents.get(c, (np.nan, np.nan))[1], 1)
        d['centroid_y'] = round(cents.get(c, (np.nan, np.nan))[0], 1)
        d['touches_border'] = by[row['cell']]['touches_border']
        d['weak_border_with'] = by[row['cell']]['weak_border_with']
        out.append(d)
    used['n_cells'] = len(rois)
    used['n_analysed'] = len(rows)
    used['n_edge'] = sum(r['status'] == 'edge' for r in rois)
    used['n_weak'] = sum(r['status'] == 'binucleate' for r in rois)
    used['n_mito'] = len(mito_rows)
    return MitoResult(settings=s.to_dict(), cells=out, mito=mito_rows, puncta=puncta_rows, used=used,
                      layers=dict(mito=b, skeleton=sk, ends=end, junctions=junc, puncta=plab > 0), mlab=mlab)


# ---- column catalogue (Mito Analyzer stats.py) -----------------------------------------------------

def catalogue():
    """(cell X, cell Y, mito X, mito Y) column lists with Mito Analyzer's display names."""
    from .mitoan.stats import CELL_X, CELL_Y, MITO_X, MITO_Y
    return CELL_X, CELL_Y, MITO_X, MITO_Y


def labels():
    out = {}
    for lst in catalogue():
        for col, name in lst:
            out.setdefault(col, name)
    return out


def column_sets(kind):
    cx, cy, mx, my = catalogue()
    if kind == 'cell':
        return {'미토 형태': [c for c, _ in cx], '관심 단백질': [c for c, _ in cy]}
    if kind == 'mito':
        return {'조각 형태': [c for c, _ in mx], '조각 위 green': [c for c, _ in my]}
    return {}


# ---- Mito Analyzer CSV files ---------------------------------------------------------------------------

def _num(v):
    if v in ('', None):
        return v
    if v in ('True', 'False'):
        return v == 'True'
    try:
        return float(v)
    except (TypeError, ValueError):
        return v


def read_csv(path):
    with open(path, newline='', encoding='utf-8-sig') as f:
        return [{k: _num(v) for k, v in r.items()} for r in csv.DictReader(f)]


def is_per_cell_csv(path) -> bool:
    try:
        with open(path, newline='', encoding='utf-8-sig') as f:
            head = next(csv.reader(f))
    except (OSError, StopIteration, UnicodeDecodeError):
        return False
    return 'cell' in head and 'footprint_fraction' in head and 'n_networks' in head


def write_csv(path, rows):
    """Mito Analyzer's number format (pipeline._fmt)."""
    if not rows:
        return False
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)

    def fmt(v):
        if isinstance(v, float):
            return f'{v:.3e}' if v and abs(v) < 1e-3 else f'{v:.4f}'
        return v
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, keys, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: fmt(r.get(k, '')) for k in keys})
    return True


def correlations(cells, mito):
    from .mitoan.stats import correlation_table
    return correlation_table(cells, mito)
