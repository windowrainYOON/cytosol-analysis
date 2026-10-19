"""Intensity measurement per cell ROI, and particle ROIs thresholded inside each cell.

Every cell gives the regions ``cell``, ``nuc`` (nucleus), ``cyto`` (cell minus
nucleus) and, when particles are defined, ``particle``. Further regions are
set expressions over these names (``cyto - particle``, ``cell & particle``,
``(cell - nuc) | particle``), evaluated per cell.

Values are ImageJ's Measure on the raw pixels of the region: Area, Mean,
StdDev (n - 1), Min, Max, IntDen (= Area × Mean, calibrated) and RawIntDen
(sum of the pixel values).

Particles are found inside each cell's cytosol (or whole cell); particles
smaller than a minimum size are dropped (ImageJ Analyze Particles).

* Manual: the pixels at or above one raw threshold, split into 8-connected
  particles.
* Automatic (spot detection, after the ParticleTracker detector): spot
  centres are where the scale-normalised Hessian's smaller curvature (high
  for round spots, not for cell or nucleus edges) and the background-
  subtracted intensity both exceed the cell's median + k × MAD; each spot
  then grows by watershed over the background-subtracted image (grey
  opening, rolling-ball like) down to a fraction of its own peak, so touching
  spots stay separate and dim spots next to bright ones are kept.
* Legacy ``otsu`` settings (v0.13 files) still give what the ImageJ macro
  ``setAutoThreshold("Otsu dark")`` gives with that cell's ROI selected:
  8-bit data use the ROI's 256-bin histogram; 16- and 32-bit data are first
  scaled to 8 bits over the whole plane's min..max (``convertToByte``), and the
  8-bit level is mapped back to a raw value.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

BASE_REGIONS = ('cell', 'nuc', 'cyto', 'particle')
REGION_TITLES = {'cell': '세포', 'nuc': '핵', 'cyto': '세포질', 'particle': '입자'}
ALIASES = {'cell': 'cell', 'nuc': 'nuc', 'nucleus': 'nuc', 'cyto': 'cyto', 'cytosol': 'cyto',
           'particle': 'particle', 'particles': 'particle', 'part': 'particle'}
STATS = ('Mean', 'StdDev', 'Min', 'Max', 'IntDen', 'RawIntDen')
INT_NOTE = re.compile(r'^(u?int)(8|16|32)$|^(\d+)-bit$')
PARTICLE_PREFIX = 'part'
REGION_PREFIX = 'rgn'


# ---------------------------------------------------------------------------
# region expressions
# ---------------------------------------------------------------------------


class ExpressionError(ValueError):
    pass


_TOKEN = re.compile(r'\s*(?:([A-Za-z_]+)|(.))')


def _tokens(text):
    out = []
    for name, op in _TOKEN.findall(text):
        if name:
            key = ALIASES.get(name.lower())
            if key is None:
                raise ExpressionError(f'알 수 없는 이름: {name} (cell, nuc, cyto, particle)')
            out.append(('name', key))
        elif op.strip():
            o = {'∩': '&', '∪': '|', '+': '|', '−': '-', '*': '&'}.get(op, op)
            if o not in '&|-()':
                raise ExpressionError(f'알 수 없는 기호: {op} (&, |, -, 괄호)')
            out.append(('op', o))
    return out


def parse_region(text: str):
    """Expression -> nested tuples ('name', key) / (op, left, right).

    ``&`` (intersection) binds tighter than ``|`` (union) and ``-`` (difference),
    which are evaluated left to right."""
    toks = _tokens(text)
    if not toks:
        raise ExpressionError('빈 식')
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else (None, None)

    def atom():
        nonlocal pos
        kind, v = peek()
        if kind == 'name':
            pos += 1
            return ('name', v)
        if v == '(':
            pos += 1
            node = union()
            if peek()[1] != ')':
                raise ExpressionError('닫는 괄호가 없습니다')
            pos += 1
            return node
        raise ExpressionError('식이 올바르지 않습니다')

    def inter():
        nonlocal pos
        node = atom()
        while peek()[1] == '&':
            pos += 1
            node = ('&', node, atom())
        return node

    def union():
        nonlocal pos
        node = inter()
        while peek()[1] in ('|', '-'):
            op = peek()[1]
            pos += 1
            node = (op, node, inter())
        return node

    tree = union()
    if pos != len(toks):
        raise ExpressionError('식이 올바르지 않습니다')
    return tree


def region_names(tree) -> set[str]:
    if tree[0] == 'name':
        return {tree[1]}
    return region_names(tree[1]) | region_names(tree[2])


def eval_region(tree, masks: dict) -> np.ndarray:
    if tree[0] == 'name':
        return masks[tree[1]]
    a, b = eval_region(tree[1], masks), eval_region(tree[2], masks)
    return a & b if tree[0] == '&' else a | b if tree[0] == '|' else a & ~b


def region_label(text: str) -> str:
    """Canonical text of an expression (also the CSV region name)."""
    def fmt(node, top=True):
        if node[0] == 'name':
            return node[1]
        s = f'{fmt(node[1], False)} {node[0]} {fmt(node[2], False)}'
        return s if top else f'({s})'
    return fmt(parse_region(text))


def base_masks(cells, particles: np.ndarray | None = None) -> dict:
    """Full-image boolean masks of every base region (pixels of any cell)."""
    lab = cells.labels
    cell = lab > 0
    nuc = (cells.nuclei == lab) & cell if cells.nuclei is not None else np.zeros_like(cell)
    part = particles & cell if particles is not None else np.zeros_like(cell)
    return {'cell': cell, 'nuc': nuc, 'cyto': cell & ~nuc, 'particle': part}


# ---------------------------------------------------------------------------
# ImageJ auto threshold
# ---------------------------------------------------------------------------


def imagej_otsu(hist) -> int:
    """ij.process.AutoThresholder Otsu on a 256-bin histogram."""
    h = np.asarray(hist, np.float64)
    k = np.arange(len(h), dtype=np.float64)
    S, N = float((k * h).sum()), float(h.sum())
    n1 = np.cumsum(h)
    sk = np.cumsum(k * h)
    best, kstar = 0.0, 0
    for i in range(1, len(h) - 1):  # BCV >= max: the last maximum wins
        denom = n1[i] * (N - n1[i])
        bcv = ((n1[i] / N) * S - sk[i]) ** 2 / denom if denom != 0 else 0.0
        if bcv >= best:
            best, kstar = bcv, i
    return kstar


def bit_depth(item, c: int) -> int:
    """8, 16 or 32: the ImageJ type of a channel as stored in the file."""
    notes = list(getattr(item.image, 'range_notes', []) or [])
    note = notes[c] if c < len(notes) else ''
    m = INT_NOTE.match(note or '')
    if m and m.group(1):
        bits = int(m.group(2))
        return 8 if bits == 8 and m.group(1) == 'uint' else 16 if bits <= 16 else 32
    if m and m.group(3):
        bits = int(m.group(3))
        return 8 if bits <= 8 else 16 if bits <= 16 else 32
    return 32


class ByteView:
    """A plane as ImageJ's setAutoThreshold sees it: 8-bit bins plus the
    mapping of a bin back to a raw threshold value."""

    def __init__(self, plane: np.ndarray, depth: int):
        self.depth = depth
        p = np.asarray(plane)
        if depth == 8:
            self.min, self.max = 0.0, 255.0
            self.bins = np.clip(np.rint(p), 0, 255).astype(np.int64)
        elif depth == 16:
            q = np.clip(np.rint(p), 0, 65535)
            lo, hi = float(q.min()), float(q.max())
            self.min, self.max = lo, hi
            scale = 256.0 / (hi - lo + 1)
            self.bins = np.clip(((q - lo) * scale + 0.5).astype(np.int64), 0, 255)
        else:
            finite = p[np.isfinite(p)]
            lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 0.0)
            self.min, self.max = lo, hi
            scale = 255.0 / (hi - lo) if hi > lo else 0.0
            v = np.where(np.isfinite(p), p, lo) - lo
            self.bins = np.clip((np.maximum(v, 0) * scale + 0.5).astype(np.int64), 0, 255)

    def lower(self, level: int) -> float:
        """Raw value of the lower threshold ``level`` (0..255; dark background)."""
        level = min(level, 255)
        if self.depth == 8:
            return float(level)
        v = self.min + level / 255.0 * (self.max - self.min) if self.max > self.min else self.min
        # ShortProcessor.setThreshold rounds to an integer (Java Math.round)
        return float(math.floor(max(v, 0.0) + 0.5)) if self.depth == 16 else v


def otsu_thresholds(plane, labels, region, depth) -> dict[int, float]:
    """setAutoThreshold("Otsu dark") within each cell's region: label -> lower value."""
    bv = ByteView(plane, depth)
    lab = labels[region]
    n = int(labels.max()) + 1
    hist = np.bincount(lab * 256 + bv.bins[region], minlength=n * 256).reshape(n, 256)
    out = {}
    for l in np.unique(lab):
        if l > 0:
            out[int(l)] = bv.lower(imagej_otsu(hist[l]) + 1)
    return out


# ---------------------------------------------------------------------------
# particles
# ---------------------------------------------------------------------------


@dataclass
class ParticleSettings:
    channel: str            # channel name (matched by name on other images)
    index: int = 0          # channel index when no channel has that name
    within: str = 'cyto'    # 'cyto', 'cell' or 'image' (whole image, no cell ROIs needed)
    method: str = 'auto'    # 'auto' (spot detection), 'manual' or 'otsu' (v0.13)
    manual: float = 0.0     # threshold when method == 'manual' (raw value)
    min_px: int = 1         # smallest particle kept (pixels)
    k: float = 3.0          # auto: spot centres above median + k × MAD
    size_um: float = 0.4    # auto: typical spot diameter
    frac: float = 0.3       # auto: spot extent down to this fraction of its peak

    def channel_for(self, item) -> int | None:
        if self.channel in item.channels:
            return item.channels.index(self.channel)
        return self.index if self.index < len(item.channels) else None

    def properties(self) -> dict:
        return {f'particle_{k}': str(v) for k, v in asdict(self).items()}

    @classmethod
    def from_properties(cls, props: dict) -> 'ParticleSettings | None':
        d = {k[len('particle_'):]: v for k, v in (props or {}).items()
             if k.startswith('particle_')}
        if 'channel' not in d:
            return None
        try:
            return cls(channel=d['channel'], index=int(d.get('index', 0)),
                       within=d.get('within', 'cyto'), method=d.get('method', 'otsu'),
                       manual=float(d.get('manual', 0)), min_px=int(d.get('min_px', 1)),
                       k=float(d.get('k', 3.0)), size_um=float(d.get('size_um', 0.4)),
                       frac=float(d.get('frac', 0.3)))
        except ValueError:
            return None


@dataclass
class Particles:
    """Particle mask of an image plane and how it was made."""

    mask: np.ndarray                     # (H, W) bool
    settings: ParticleSettings | None = None   # None: loaded from ROI files
    thresholds: dict = field(default_factory=dict)  # cell label -> threshold
    channel: int | None = None
    plane_key: object = None             # (z, t) the mask was made on
    labels: np.ndarray | None = None     # particle numbers when not just connectivity

    def components(self, cells) -> np.ndarray:
        """Particle number image: each 8-connected piece within one cell, or
        the stored particles (split touching spots, loaded ROIs)."""
        from skimage import measure
        if self.labels is not None:
            lab = np.where(self.mask, self.labels, 0).astype(np.int64)
            # one particle never spans two cells
            lab = lab * (int(cells.labels.max()) + 1) + np.where(lab > 0, cells.labels, 0)
            return np.unique(lab, return_inverse=True)[1].reshape(lab.shape).astype(np.int32)
        return measure.label(np.where(self.mask, cells.labels, 0), connectivity=2)

    def counts(self, cells) -> dict[int, int]:
        comp = self.components(cells)
        if not comp.max():
            return {}
        parent = np.zeros(comp.max() + 1, np.int64)
        parent[comp.ravel()] = cells.labels.ravel()
        c = np.bincount(parent[1:], minlength=int(cells.labels.max()) + 1)
        return {int(l): int(c[l]) for l in np.nonzero(c)[0]}


DEFAULT_PX_UM = 0.1  # spot size of uncalibrated images


def _robust(v):
    """median and MAD (scaled to σ) of the values; the std when MAD is 0."""
    med = float(np.median(v))
    mad = float(np.median(np.abs(v - med))) * 1.4826
    if mad <= 0:
        mad = float(np.std(v)) or 1e-12
    return med, mad


def spot_particles(plane, lab, region, s: ParticleSettings, px_um=None):
    """Automatic particles (see the module docstring). Returns the particle
    number image and, per cell, about the lowest raw intensity a particle
    reaches (the cell's median + 2 × noise)."""
    from scipy import ndimage as ndi
    from skimage import feature, measure, morphology, segmentation

    px = px_um or DEFAULT_PX_UM
    p = plane.astype(np.float32)
    inside = lab > 0
    if inside.any() and not inside.all():
        # outside the cells take the nearest cell pixel, so that the filters
        # below do not answer to the drop at the cell outline
        near = ndi.distance_transform_edt(~inside, return_distances=False, return_indices=True)
        p = p[tuple(near)]
    d = max(s.size_um / px, 1.0)                 # spot diameter in pixels
    sig = max(0.7, d / (2 * math.sqrt(2)))       # Gaussian scale of a spot that size
    r = max(2, int(round(2.5 * d)))              # background radius
    # background: grey opening (rolling-ball like); it keeps the step at a
    # cell edge, so edges do not stand out from it
    sm = ndi.gaussian_filter(p, 1.0)
    sub = sm - morphology.opening(sm, morphology.disk(max(2, r // 2)))
    # spot score: the smaller curvature of the scale-normalised Hessian, which
    # is high for round spots but not for edges or ridges (where the LoG is)
    hrr = ndi.gaussian_filter(p, sig, order=(2, 0))
    hcc = ndi.gaussian_filter(p, sig, order=(0, 2))
    hrc = ndi.gaussian_filter(p, sig, order=(1, 1))
    score = -(hrr + hcc + np.sqrt((hrr - hcc) ** 2 + 4 * hrc * hrc)) / 2 * sig * sig
    n = int(lab.max()) + 1
    seed_t = np.full(n, np.inf, np.float32)
    base = np.zeros(n, np.float32)
    lo = np.full(n, np.inf, np.float32)
    hi = np.full(n, np.inf, np.float32)
    cutoff = {}
    flat_lab, flat_reg = lab.ravel(), region.ravel()
    order = np.argsort(flat_lab[flat_reg], kind='stable')
    idx = np.flatnonzero(flat_reg)[order]
    labs = flat_lab[idx]
    bounds = np.flatnonzero(np.diff(labs)) + 1
    for part in np.split(idx, bounds):
        if not len(part):
            continue
        l = int(flat_lab[part[0]])
        if l == 0:
            continue
        med, mad = _robust(score.ravel()[part])
        seed_t[l] = med + s.k * mad
        med, mad = _robust(sub.ravel()[part])
        base[l], lo[l], hi[l] = med, med + 2.0 * mad, med + s.k * mad
        cutoff[l] = float(np.median(p.ravel()[part]) + 2.0 * mad)
    # a centre must also stand above the cell's background in the image itself
    # (the curvature alone also answers to single noisy pixels)
    det = region & (score > seed_t[lab]) & (sub > hi[lab])
    out = np.zeros(lab.shape, np.int32)
    if not det.any():
        return out, cutoff
    seg = measure.label(np.where(det, lab, 0), connectivity=2)
    pk = feature.peak_local_max(np.where(det, score, 0), labels=seg, exclude_border=False,
                                min_distance=max(1, int(round(0.375 * d))))
    if not len(pk):
        return out, cutoff
    marks = np.zeros(lab.shape, np.int32)
    marks[tuple(pk.T)] = np.arange(1, len(pk) + 1)
    # grow within the seed's own cell only
    cand = region & (sub > lo[lab])
    owner = np.zeros(len(pk) + 1, lab.dtype)
    owner[1:] = lab[tuple(pk.T)]
    ws = segmentation.watershed(-sub, marks, mask=cand)
    ws[(ws > 0) & (owner[ws] != lab)] = 0
    peak = np.zeros(len(pk) + 1, np.float32)
    peak[1:] = sub[tuple(pk.T)] - base[owner[1:]]
    keep = (ws > 0) & ((sub - base[lab]) >= s.frac * peak[ws])
    out[keep] = ws[keep]
    return out, cutoff


def whole_image_cells(shape, px_um=None):
    """One 'cell' covering the whole image, for particles found without cell ROIs."""
    from .cellroi import CellRois
    return CellRois(np.ones(shape, np.int32), None, px_um)


def detect_particles(cells, plane: np.ndarray, s: ParticleSettings, depth: int,
                     px_um: float | None = None) -> Particles:
    lab = cells.labels
    region = base_masks(cells)['cyto' if s.within == 'cyto' else 'cell']
    if s.method == 'auto':
        parts, thr = spot_particles(plane, lab, region, s, px_um)
        if s.min_px > 1 and parts.any():
            size = np.bincount(parts.ravel())
            small = size < s.min_px
            small[0] = False
            parts[small[parts]] = 0
        return Particles(parts > 0, s, thr, labels=parts)
    if s.method == 'manual':
        thr = {l: float(s.manual) for l in cells.ids()}
    else:
        thr = otsu_thresholds(plane, lab, region, depth)
    table = np.full(int(lab.max()) + 1, np.inf)
    for l, v in thr.items():
        table[l] = v
    mask = region & (plane >= table[lab])
    if s.min_px > 1 and mask.any():
        from skimage import measure
        comp = measure.label(np.where(mask, lab, 0), connectivity=2)
        size = np.bincount(comp.ravel())
        small = size < s.min_px
        small[0] = False
        mask &= ~small[comp]
    return Particles(mask, s, thr)


def trace_outlines(mask: np.ndarray, x0: int = 0, y0: int = 0,
                   eight: bool = False) -> list[np.ndarray]:
    """Closed polygons along the pixel edges of a mask (outer boundaries and
    holes), as (N, 2) x, y with pixel (r, c) covering [c, c+1] x [r, r+1].
    Filling them with the even-odd rule gives back exactly the mask, as in
    ImageJ (ShapeRoi is even-odd; a pixel is inside when its center is).
    eight: pixels touching at a corner stay in one outline that passes
    through that corner, as ImageJ's Wand traces particles."""
    m = np.pad(np.asarray(mask, bool), 1)
    nxt = {}
    # edges run clockwise on screen (foreground on the right)
    for (dr, dc), (a, b) in (((-1, 0), ((0, 0), (1, 0))),    # top: west -> east
                             ((0, 1), ((1, 0), (1, 1))),     # right: north -> south
                             ((1, 0), ((1, 1), (0, 1))),     # bottom: east -> west
                             ((0, -1), ((0, 1), (0, 0)))):   # left: south -> north
        edge = m[1:-1, 1:-1] & ~m[1 + dr:m.shape[0] - 1 + dr, 1 + dc:m.shape[1] - 1 + dc]
        for r, c in zip(*np.nonzero(edge)):
            p = (c + a[0], r + a[1])
            q = (c + b[0], r + b[1])
            nxt.setdefault(p, []).append(q)
    loops = []
    while nxt:
        start = next(iter(nxt))
        if eight:  # not a corner the outline passes twice
            start = next((p for p, q in nxt.items() if len(q) == 1), start)
        pts = [start]
        cur, d = start, None
        while True:
            outs = nxt[cur]
            if len(outs) > 1 and d is not None:
                # where two pixels touch at a corner, turn toward the
                # foreground so every loop is simple (or away, eight)
                turn = (d[1], -d[0]) if eight else (-d[1], d[0])
                pick = next((q for q in outs if (q[0] - cur[0], q[1] - cur[1]) == turn), outs[0])
            else:
                pick = outs[0]
            outs.remove(pick)
            if not outs:
                del nxt[cur]
            d = (pick[0] - cur[0], pick[1] - cur[1])
            cur = pick
            if cur == start:
                break
            pts.append(cur)
        xy = np.asarray(pts, float)
        # drop points in the middle of straight runs
        prev, after = np.roll(xy, 1, 0), np.roll(xy, -1, 0)
        cross = (xy[:, 0] - prev[:, 0]) * (after[:, 1] - xy[:, 1]) \
            - (xy[:, 1] - prev[:, 1]) * (after[:, 0] - xy[:, 0])
        xy = xy[cross != 0]
        loops.append(xy + (x0, y0))
    return loops


def particle_rois(cells, particles: Particles, properties=None) -> list:
    """One ImageJ ROI per particle, named partCCC-NN (cell number, particle);
    a particle with holes becomes a composite ROI. The outlines follow the
    pixel edges, so ImageJ's mask of each ROI is exactly the particle, and
    they are traced ROIs, so ImageJ measures the same perimeter as Analyze
    Particles."""
    import roifile

    from .cellroi import _composite_roi

    comp = particles.components(cells)
    out = []
    props = dict(properties or {})
    if particles.settings is not None:
        props.update(particles.settings.properties())
    for k, _, name, sl in particle_names(cells, comp):
        loops = wand_outlines(comp[sl] == k, sl[1].start, sl[0].start)
        if len(loops) == 1:
            roi = roifile.ImagejRoi.frompoints(np.round(loops[0]).astype(np.int32), name=name)
            roi.roitype = roifile.ROI_TYPE.TRACED
        else:
            roi = _composite_roi(loops, name)
        roi.properties = dict(props)
        out.append(roi)
    return out


def save_particles(path, cells, particles: Particles, properties=None) -> str:
    import roifile

    rois = particle_rois(cells, particles, properties)
    if not rois:
        raise ValueError('저장할 입자 ROI가 없습니다.')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    roifile.roiwrite(path, rois)
    return str(path)


def is_particle_file(path) -> bool:
    """An ImageJ ROI file holding only particle ROIs (partCCC-NN)."""
    import roifile

    try:
        r = roifile.roiread(path)
    except Exception:
        return False
    rois = r if isinstance(r, list) else [r]
    return bool(rois) and all((x.name or '').lower().startswith(PARTICLE_PREFIX) for x in rois)


def load_particles(path, shape) -> tuple[Particles, ParticleSettings | None]:
    """Particle ROIs back into a mask, and the settings stored in them."""
    import roifile

    from .cellroi import CellRois, _roi_polygons

    r = roifile.roiread(path)
    rois = r if isinstance(r, list) else [r]
    tmp = CellRois(np.zeros(shape, np.int32))
    labels = np.zeros(shape, np.int32)
    settings = None
    for k, roi in enumerate(rois, start=1):
        m = np.zeros(shape, bool)
        for poly in _roi_polygons(roi):  # even-odd, like ImageJ's ShapeRoi
            m ^= tmp.polygon_mask(poly)
        labels[m] = k
        settings = settings or ParticleSettings.from_properties(roi.properties or {})
    return Particles(labels > 0, None, {}, None, labels=labels), settings


def region_masks(cells, regions: list['Region'], particles: Particles | None = None
                 ) -> list[tuple['Region', np.ndarray]]:
    """Full-image mask of each region, inside the cells."""
    masks = base_masks(cells, particles.mask if particles is not None else None)
    return [(r, eval_region(r.tree, masks) & masks['cell']) for r in regions]


def region_outlines(cells, regions, particles=None) -> list[np.ndarray]:
    """Pixel-edge outlines of every region, each cell traced on its own."""
    from scipy import ndimage as ndi

    loops = []
    for _, m in region_masks(cells, regions, particles):
        lab = np.where(m, cells.labels, 0)
        for l, sl in enumerate(ndi.find_objects(lab), start=1):
            if sl is not None:
                loops += trace_outlines(lab[sl] == l, sl[1].start, sl[0].start)
    return loops


def region_rois(cells, regions, particles=None, properties=None) -> list:
    """One ImageJ ROI per cell and region, named rgnCCC-R (cell, region
    number), with the expression in its ``region`` property."""
    from .cellroi import _composite_roi, _polygon_roi

    out = []
    for k, (r, m) in enumerate(region_masks(cells, regions, particles), start=1):
        for l in cells.ids():
            cm = m & (cells.labels == l)
            if not cm.any():
                continue
            rows, cols = np.nonzero(cm)
            r0, c0 = rows.min(), cols.min()
            loops = trace_outlines(cm[r0:rows.max() + 1, c0:cols.max() + 1], c0, r0)
            name = f'{REGION_PREFIX}{l:03d}-{k}'
            roi = _polygon_roi(loops[0], name) if len(loops) == 1 else _composite_roi(loops, name)
            roi.properties = {**(properties or {}), 'region': r.name}
            out.append(roi)
    return out


def save_regions(path, cells, regions, particles=None, properties=None) -> str | None:
    import roifile

    rois = region_rois(cells, regions, particles, properties)
    if not rois:
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    roifile.roiwrite(path, rois)
    return str(path)


def is_region_file(path) -> bool:
    """An ImageJ ROI file holding only logic-region ROIs (rgnCCC-R)."""
    import roifile

    try:
        r = roifile.roiread(path)
    except Exception:
        return False
    rois = r if isinstance(r, list) else [r]
    return bool(rois) and all((x.name or '').lower().startswith(REGION_PREFIX) for x in rois)


# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------


@dataclass
class Region:
    name: str      # CSV name: cell, nucleus, cytosol, particle or the expression
    tree: tuple


def make_regions(base: list[str], expressions: list[str]) -> list[Region]:
    names = {'cell': 'cell', 'nuc': 'nucleus', 'cyto': 'cytosol', 'particle': 'particle'}
    out = [Region(names[b], ('name', b)) for b in base]
    seen = {r.name for r in out}
    for e in expressions:
        e = e.strip()
        if not e:
            continue
        tree = parse_region(e)
        name = region_label(e)
        if tree[0] == 'name':
            name = names[tree[1]]
        if name not in seen:
            out.append(Region(name, tree))
            seen.add(name)
    return out


def measure_cells(planes: np.ndarray, cells, regions: list[Region], channels: list[str],
                  px_um: float | None, particles: Particles | None = None,
                  channel_index: list[int] | None = None, stats=('Mean',)) -> list[dict]:
    """One row per cell and region; per channel the chosen ImageJ Measure values."""
    from scipy import ndimage as ndi

    lab = cells.labels
    ids = cells.ids()
    n = int(lab.max()) + 1 if ids else 1
    masks = base_masks(cells, particles.mask if particles is not None else None)
    chans = list(range(len(channels))) if channel_index is None else list(channel_index)
    counts = particles.counts(cells) if particles is not None else {}
    px2 = px_um ** 2 if px_um else 1.0
    rows = {(l, r.name): None for l in ids for r in regions}
    for r in regions:
        m = eval_region(r.tree, masks) & masks['cell']
        lm = lab[m]
        npx = np.bincount(lm, minlength=n)
        vals = {}
        for c in chans:
            v = planes[c][m].astype(np.float64)
            s = np.bincount(lm, weights=v, minlength=n)
            vals[c] = (s, np.bincount(lm, weights=v * v, minlength=n), v)
        present = [l for l in ids if npx[l]]
        mins = {c: dict(zip(present, np.atleast_1d(ndi.minimum(vals[c][2], lm, present))))
                for c in chans if present and ('Min' in stats)}
        maxs = {c: dict(zip(present, np.atleast_1d(ndi.maximum(vals[c][2], lm, present))))
                for c in chans if present and ('Max' in stats)}
        for l in ids:
            a = int(npx[l])
            row = {'roi': f'cell{l:03d}', 'status': cells.status.get(l, 'ok'), 'region': r.name,
                   'area_px': a, 'area_um2': round(a * px2, 4) if px_um else ''}
            if particles is not None:
                row['n_particles'] = counts.get(l, 0)
                row['particle_threshold'] = _fmt(particles.thresholds.get(l))
            for c in chans:
                s, sq, _ = vals[c]
                name = channels[c]
                mean = s[l] / a if a else math.nan
                if a > 1:
                    sd = math.sqrt(max((sq[l] - s[l] * s[l] / a) / (a - 1), 0.0))
                else:
                    sd = 0.0 if a else math.nan
                out = {'Mean': mean, 'StdDev': sd,
                       'Min': mins.get(c, {}).get(l, math.nan) if a else math.nan,
                       'Max': maxs.get(c, {}).get(l, math.nan) if a else math.nan,
                       'IntDen': a * px2 * mean if a else math.nan,
                       'RawIntDen': s[l] if a else math.nan}
                for k in STATS:
                    if k in stats:
                        row[f'{name}_{k}'] = _fmt(out[k])
            rows[(l, r.name)] = row
    return [rows[(l, r.name)] for l in ids for r in regions]


# ---------------------------------------------------------------------------
# per-particle shape (ImageJ Analyze Particles)
# ---------------------------------------------------------------------------

# ImageJ Set Measurements groups and the extra condensate measures, in table order
SHAPES = ('Centroid', 'Perim.', 'Circ.', 'Solidity', 'AR', 'Round', 'Feret', 'Ellipse',
          'EqDiam', 'NND', 'Partition')
SHAPE_TITLES = {
    'Centroid': ('중심 X, Y', '입자 픽셀 중심의 평균 위치 (ImageJ Centroid)'),
    'Perim.': ('둘레', 'ImageJ가 입자 외곽선(traced ROI)에서 재는 둘레: 대각선 모서리를 깎은 픽셀 경계 길이'),
    'Circ.': ('원형도', '4π × 면적 / 둘레² (ImageJ Circ.). 1 = 완전한 원, 0에 가까울수록 길쭉하거나 울퉁불퉁'),
    'Solidity': ('Solidity', '면적 / 볼록 껍질(convex hull) 면적 (ImageJ). 1 = 오목한 곳 없음; '
                 '낮으면 여러 방울이 붙었거나 응집체(gel/aggregate)처럼 불규칙'),
    'AR': ('종횡비 (AR)', '맞춘 타원의 장축 / 단축 (ImageJ AR). 1 = 둥근 방울'),
    'Round': ('Roundness', '4 × 면적 / (π × 장축²) = 1 / AR (ImageJ Round)'),
    'Feret': ('Feret 지름', '가장 긴 지름 Feret, 가장 짧은 폭 MinFeret, Feret 각도 (ImageJ Feret\'s diameter)'),
    'Ellipse': ('타원 (장·단축, 각도)', '같은 면적·2차 모멘트의 타원 장축 Major, 단축 Minor, 각도 (ImageJ Fit ellipse)'),
    'EqDiam': ('등가 지름', '같은 면적의 원 지름 2√(면적/π)'),
    'NND': ('최근접 입자 거리', '같은 세포(이미지 전체 모드는 이미지)에서 가장 가까운 다른 입자 중심까지 거리'),
    'Partition': ('분배계수', '채널마다 입자 평균 / 같은 세포 묽은 상(입자를 찾은 영역에서 입자를 뺀 곳) 평균. '
                  '배경을 빼지 않은 원시값의 비'),
}


def traced_perimeter(xy: np.ndarray) -> float:
    """ImageJ PolygonRoi.getTracedPerimeter of a pixel-edge outline (pixels)."""
    n = len(xy)
    if n < 4:
        return 0.0
    d = np.diff(np.vstack([xy[-1:], xy]), axis=0)  # d[i] = xy[i] - xy[i-1]
    side = np.abs(d).sum(1)
    corners, corner = 0, False
    for i in range(n):
        if side[i] > 1 or not corner:
            corner = True
            corners += 1
        else:
            corner = False
    return float(np.abs(d).sum() - corners * (2 - math.sqrt(2)))


def _hull(pts: np.ndarray) -> np.ndarray:
    """Convex hull vertices (monotone chain), no duplicates."""
    pts = np.unique(pts, axis=0)
    if len(pts) < 3:
        return pts

    def half(ps):
        out = []
        for p in ps:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(tuple(p))
        return out

    lo, hi = half(pts), half(pts[::-1])
    hull = np.asarray(lo[:-1] + hi[:-1], float)[::-1]
    # ImageJ's order (FloatPolygon.getConvexHull: clockwise on screen from the
    # topmost-leftmost point), which picks among equal Feret diameters
    start = np.lexsort((hull[:, 0], hull[:, 1]))[0]
    return np.roll(hull, -start, axis=0)


def _polygon_area(xy) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return abs(float(np.sum(x * np.roll(y, 1) - np.roll(x, 1) * y))) / 2


def feret_values(hull: np.ndarray) -> tuple[float, float, float]:
    """ImageJ Roi.getFeretValues: Feret, FeretAngle, MinFeret (pixels, degrees)."""
    if len(hull) < 2:
        return 0.0, 0.0, 0.0
    diff = hull[:, None, :] - hull[None, :, :]
    d2 = (diff ** 2).sum(-1)
    i, j = np.unravel_index(np.argmax(np.triu(d2, 1)), d2.shape)
    if hull[i, 0] > hull[j, 0]:
        i, j = j, i
    angle = math.degrees(math.atan2(hull[i, 1] - hull[j, 1], hull[j, 0] - hull[i, 0]))
    if angle < 0:
        angle += 180
    feret = math.sqrt(d2[i, j])
    min_feret = math.inf
    for k in range(len(hull)):
        a, b = hull[k - 1], hull[k]
        nrm = np.array([b[1] - a[1], a[0] - b[0]], float)
        ln = math.hypot(*nrm)
        if ln == 0:
            continue
        # every hull point lies on one side of a hull edge
        min_feret = min(min_feret, float(np.abs((hull - b) @ nrm).max() / ln))
    return feret, angle, (min_feret if math.isfinite(min_feret) else 0.0)


HALFPI = 1.5707963267949  # ImageJ EllipseFitter's constant


def fit_ellipse(m: np.ndarray) -> tuple[float, float, float]:
    """ImageJ EllipseFitter on a mask: Major, Minor (pixels), Angle (degrees,
    counter-clockwise from the x axis)."""
    # the same sums and float operations as ImageJ: for symmetric shapes u11
    # is a rounding residue that sets the angle, and ImageJ keeps it
    ys, xs = np.nonzero(m)
    n = len(xs)
    xsum, ysum = float(xs.sum()), float(ys.sum())
    x2sum, y2sum = float((xs * xs).sum()), float((ys * ys).sum())
    xysum = float((xs * ys).sum())
    x2sum += 0.08333333 * n
    y2sum += 0.08333333 * n
    x1, y1 = xsum / n, ysum / n
    u20 = x2sum / n - x1 * x1
    u02 = y2sum / n - y1 * y1
    u11 = xysum / n - x1 * y1
    m4 = max(4.0 * abs(u02 * u20 - u11 * u11), 1e-6)
    a11, a12, a22 = u02 / m4, u11 / m4, u20 / m4
    tmp = a11 - a22 or 1e-6
    theta = 0.5 * math.atan(2.0 * a12 / tmp)
    if theta < 0:
        theta += HALFPI
    if a12 > 0:
        theta += HALFPI
    elif a12 == 0:
        if a22 > a11:
            theta = 0.0
            a11, a22 = a22, a11
        elif a11 != a22:
            theta = HALFPI
    tmp = math.sin(theta) or 1e-6
    z = a12 * math.cos(theta) / tmp
    major = math.sqrt(1.0 / abs(a22 + z))
    minor = math.sqrt(1.0 / abs(a11 - z))
    scale = math.sqrt(n / (math.pi * major * minor))  # same area as the particle
    major, minor = major * scale * 2, minor * scale * 2
    angle = 180.0 * theta / math.pi
    if angle == 180.0:
        angle = 0.0
    return max(major, minor), min(major, minor), angle


def wand_outlines(m: np.ndarray, x0: int = 0, y0: int = 0) -> list[np.ndarray]:
    """Pixel-edge outlines of a particle as ImageJ's Wand traces it: pixels
    touching at a corner in one outline, which ends at the right end of the
    first run of the top row (ImageJ's traced perimeter depends on where the
    outline starts)."""
    loops = trace_outlines(m, eight=True)
    r0 = int(np.argmax(m.any(1)))
    c0 = int(np.argmax(m[r0]))
    c1 = c0 + int(np.argmin(np.append(m[r0, c0:], False)))
    for i, l in enumerate(loops):
        hit = np.nonzero((l[:, 0] == c1) & (l[:, 1] == r0))[0]
        if len(hit):
            loops[i] = np.roll(l, -(hit[0] + 1), axis=0)
    return [l + (x0, y0) for l in loops]


def particle_shape(m: np.ndarray) -> dict:
    """ImageJ Analyze Particles shape values of one particle mask, in pixels:
    area and ellipse from its pixels (holes excluded), perimeter, convex hull
    and Feret from its outer outline."""
    area = int(m.sum())
    loops = wand_outlines(m)
    outer = [l for l in loops if _signed_area(l) > 0] or loops
    perim = sum(traced_perimeter(l) for l in outer)
    hull = _hull(np.concatenate(outer))
    hull_area = _polygon_area(hull) if len(hull) >= 3 else float(area)
    feret, feret_angle, min_feret = feret_values(hull)
    major, minor, angle = fit_ellipse(m)
    ys, xs = np.nonzero(m)
    return {'area': area, 'x': xs.mean() + 0.5, 'y': ys.mean() + 0.5, 'perim': perim,
            'circ': min(4 * math.pi * area / perim ** 2, 1.0) if perim else 0.0,
            'solidity': area / hull_area if hull_area else math.nan,
            'major': major, 'minor': minor, 'angle': angle,
            'ar': major / minor if minor else math.nan,
            'round': 4 * area / (math.pi * major * major) if major else math.nan,
            'feret': feret, 'feret_angle': feret_angle, 'min_feret': min_feret,
            'eq_diam': 2 * math.sqrt(area / math.pi)}


def _signed_area(xy) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)) / 2


def particle_names(cells, comp) -> list[tuple[int, int, str, tuple]]:
    """(component number, cell label, partCCC-NN, slice) in the order of
    particle_rois, so table rows and saved ROIs share names."""
    from scipy import ndimage as ndi

    out, count = [], {}
    for k, sl in enumerate(ndi.find_objects(comp), start=1):
        if sl is None:
            continue
        l = int(cells.labels[sl][comp[sl] == k][0])
        count[l] = count.get(l, 0) + 1
        out.append((k, l, f'{PARTICLE_PREFIX}{l:03d}-{count[l]:02d}', sl))
    return out


def measure_particles(planes: np.ndarray, cells, particles: Particles, channels: list[str],
                      px_um: float | None, channel_index: list[int] | None = None,
                      stats=('Mean',), shapes=SHAPES, within: str = 'cyto') -> list[dict]:
    """One row per particle: ImageJ Analyze Particles shape values, the chosen
    Measure values per channel and, for condensates, the nearest-neighbour
    distance and the partition coefficient (particle mean / mean of the rest
    of the cell's search region, the dilute phase)."""
    comp = particles.components(cells)
    names = particle_names(cells, comp)
    if not names:
        return []
    chans = list(range(len(channels))) if channel_index is None else list(channel_index)
    cal = px_um or 1.0
    unit = 'um' if px_um else 'px'
    lab = cells.labels
    n = int(lab.max()) + 1
    dilute = base_masks(cells)['cyto' if within == 'cyto' else 'cell'] & ~particles.mask
    dl = lab[dilute]
    dn = np.bincount(dl, minlength=n)
    dmean = {}
    if 'Partition' in shapes:
        for c in chans:
            s = np.bincount(dl, weights=planes[c][dilute].astype(np.float64), minlength=n)
            with np.errstate(divide='ignore', invalid='ignore'):
                dmean[c] = s / dn
    shp = {k: particle_shape(comp[sl] == k) for k, _, _, sl in names}
    nnd = {}
    if 'NND' in shapes:
        by_cell = {}
        for k, l, _, sl in names:
            by_cell.setdefault(l, []).append(
                (k, shp[k]['x'] + sl[1].start, shp[k]['y'] + sl[0].start))
        for pts in by_cell.values():
            xy = np.array([(x, y) for _, x, y in pts])
            d = np.sqrt(((xy[:, None] - xy[None]) ** 2).sum(-1))
            np.fill_diagonal(d, np.inf)
            for (k, _, _), v in zip(pts, d.min(1)):
                nnd[k] = v * cal if np.isfinite(v) else math.nan
    rows = []
    for k, l, name, sl in names:
        m = comp[sl] == k
        g = shp[k]
        a = g['area']
        row = {'roi': f'cell{l:03d}', 'status': cells.status.get(l, 'ok'), 'particle': name,
               'area_px': a, 'area_um2': round(a * cal * cal, 6) if px_um else ''}
        if 'Centroid' in shapes:
            row[f'x_{unit}'] = _fmt((g['x'] + sl[1].start) * cal)
            row[f'y_{unit}'] = _fmt((g['y'] + sl[0].start) * cal)
        if 'Perim.' in shapes:
            row[f'perimeter_{unit}'] = _fmt(g['perim'] * cal)
        if 'Circ.' in shapes:
            row['circularity'] = _fmt(g['circ'])
        if 'Solidity' in shapes:
            row['solidity'] = _fmt(g['solidity'])
        if 'AR' in shapes:
            row['aspect_ratio'] = _fmt(g['ar'])
        if 'Round' in shapes:
            row['roundness'] = _fmt(g['round'])
        if 'Feret' in shapes:
            row[f'feret_{unit}'] = _fmt(g['feret'] * cal)
            row[f'min_feret_{unit}'] = _fmt(g['min_feret'] * cal)
            row['feret_angle'] = _fmt(g['feret_angle'])
        if 'Ellipse' in shapes:
            row[f'major_{unit}'] = _fmt(g['major'] * cal)
            row[f'minor_{unit}'] = _fmt(g['minor'] * cal)
            row['ellipse_angle'] = _fmt(g['angle'])
        if 'EqDiam' in shapes:
            row[f'eq_diameter_{unit}'] = _fmt(g['eq_diam'] * cal)
        if 'NND' in shapes:
            row[f'nnd_{unit}'] = _fmt(nnd.get(k))
        for c in chans:
            v = planes[c][sl][m].astype(np.float64)
            mean = float(v.mean())
            out = {'Mean': mean, 'StdDev': float(v.std(ddof=1)) if a > 1 else 0.0,
                   'Min': float(v.min()), 'Max': float(v.max()),
                   'IntDen': a * cal * cal * mean, 'RawIntDen': float(v.sum())}
            for st in STATS:
                if st in stats:
                    row[f'{channels[c]}_{st}'] = _fmt(out[st])
            if 'Partition' in shapes:
                dm = dmean[c][l]
                row[f'{channels[c]}_partition'] = _fmt(mean / dm if dn[l] and dm else math.nan)
        rows.append(row)
    return rows


def _fmt(v):
    if v is None:
        return ''
    v = float(v)
    if math.isnan(v):
        return ''
    if math.isinf(v):
        return ''
    return round(v, 6)


def write_rows(path, rows) -> int:
    """CSV with the union of the rows' columns (UTF-8 with BOM for Excel)."""
    if not rows:
        return 0
    fields = []
    for row in rows:
        for k in row:
            if k not in fields:
                fields.append(k)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=fields, restval='')
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def overlay_image(rgb: np.ndarray, cells, particles: Particles | None = None,
                  selected: int = 0, regions: list | None = None) -> np.ndarray:
    """uint8 RGB with cell (yellow), nucleus (white), particle (magenta) and
    logic-region (cyan) outlines."""
    from skimage.segmentation import find_boundaries

    img = np.asarray(rgb)
    if img.dtype != np.uint8:
        img = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    img = img.copy()
    img[find_boundaries(cells.labels, mode='inner')] = (255, 220, 0)
    if cells.nuclei is not None:
        nuc = np.where(cells.nuclei == cells.labels, cells.nuclei, 0)
        img[find_boundaries(nuc, mode='inner')] = (255, 255, 255)
    if particles is not None and particles.mask.any():
        img[find_boundaries(particles.components(cells), mode='inner')] = (255, 0, 255)
    for _, m in region_masks(cells, regions or [], particles):
        img[find_boundaries(np.where(m, cells.labels, 0), mode='inner')] = (0, 255, 255)
    return img
